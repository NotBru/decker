"""Deck construction: from glosses to cards.

Every gloss becomes the design's pair -- a recognition card, which shows the
term and asks what it means, and a production card, which shows the meaning
and asks for the term. The glosses that explain the machinery rather than a
word -- a concept read from the glossary, a morphological rule -- are the
exception and get the recognition card alone; a symbol card, whose term is a
character and not a name decker wrote, keeps the pair. The pair is the reason a
gloss carries one sense and not a page's worth: two cards per sense is a deck a
learner can answer, two cards per page is a card with a list on the back.

The prose on a card is Wiktionary's, so it is written in the edition's
language; when the mother language is not that one it goes through the
translator on its way onto the card, which is where the design puts it. The
titles decker writes itself -- a concept's, a rule's -- are English for the
same reason and go the same way, :func:`_titled` below.
"""

from __future__ import annotations

import re
import sys
import unicodedata
from collections import defaultdict
from dataclasses import dataclass, field, replace

from decker import script
from decker.console import console, count, log
from decker.glosses import Gloss, is_marked, leading_qualifier
from decker.ollama import default_model
from decker.pages import Example
from decker.translation import SOURCE_LANG, SOURCE_LANGUAGE, Translator

RECOGNITION = "recognition"
PRODUCTION = "production"

#: What stands in for the character on the question side of a symbol's
#: production card. U+25A0 BLACK SQUARE, the shape a font shows when it has
#: nothing to show: it reads as *a character goes here* in every script, it is
#: in no alphabet decker teaches, and it cannot be mistaken for the answer the
#: way a Latin underscore or a `?` could in a deck that also teaches
#: punctuation. Bru's call, 2026-09-18.
MASK = "\u25a0"


@dataclass(frozen=True)
class Side:
    """One face of a card: only the pieces the design puts on that face."""

    term: str | None = None
    definition: str | None = None
    #: The example sentences, in the language being taught and nothing else:
    #: the challenge side carries them without their rendering, because the
    #: rendering *is* the answer. `[la] servilleta -- the napkin` on the front
    #: of a recognition card asks the learner to recall a word the card has
    #: already told them.
    examples: tuple[Example, ...] = ()
    #: The renderings of those sentences, in the same order, on the answer
    #: side. Kept as their own field rather than a second copy of the examples
    #: so the back does not repeat the sentences the front already shows.
    renderings: tuple[str, ...] = ()
    ipa: tuple[str, ...] = ()
    #: How the character is read, where the term is a character and the
    #: language reads it more than one way: `Kan-on: けつ (ketsu, Jōyō)`. It
    #: sits with the transcription, on the answers of both cards, and for the
    #: same reason -- it is how the term is said, and a front carrying it
    #: would be answering the production card it heads.
    readings: tuple[str, ...] = ()
    etymology: str | None = None
    #: Cached sound files, on the answers of both cards: the recognition
    #: card's back names the pronunciation next to the reading, and the
    #: production card's back is the word itself.
    audios: tuple[str, ...] = ()
    #: The mother tongue's own word for the sense, shown immediately above
    #: the definition wherever the definition is shown. Only a deck whose
    #: target language is the edition's own has one -- see
    #: :func:`_equivalent` -- and only then when the mother tongue is not
    #: that language either.
    equivalent: str = ""
    #: How Wiktionary announces the word -- gender and paradigm. On the
    #: answers of both cards: it is part of knowing the word, not part of the
    #: question, and a recognition card showing `f (plural servilletas)` on
    #: its front would be answering half of itself.
    headword: str = ""


@dataclass(frozen=True)
class Card:
    """One card: a challenge, its answer, and what must come before it."""

    #: Position in the list deck construction produced, and the card's
    #: identity: shuffling reorders the list without renumbering it.
    index: int
    #: ``RECOGNITION`` or ``PRODUCTION``.
    kind: str
    #: Index of the gloss this card teaches.
    gloss: int
    #: The Wiktionary page the gloss was read from, for the card's credit line.
    entry: str
    #: The language section it was read from, as Wiktionary names it.
    language: str
    challenge: Side
    answer: Side
    #: Indexes of the cards this one must appear after.
    depends_on: tuple[int, ...] = ()
    #: The gloss's :func:`decker.glosses.gloss_key`, written into the deck so
    #: a later run can tell what this deck already teaches.
    key: str = ""
    #: Where in `Appendix:Glossary` a concept card's entry lives, so its credit
    #: links to the entry rather than to the top of a very long page. Empty for
    #: a card teaching a word.
    anchor: str = ""
    #: Where this card's prose came from, when it is not Wiktionary's. Carried
    #: from the gloss; only a morphological rule has one.
    attribution: str = ""


@dataclass
class _Builder:
    """Accumulates cards, and remembers which card teaches which gloss."""

    cards: list[Card] = field(default_factory=list)
    #: Gloss index to the index of the recognition card that introduces it.
    introduced_by: dict[int, int] = field(default_factory=dict)

    def add(self, **fields) -> int:
        index = len(self.cards)
        self.cards.append(Card(index=index, **fields))
        return index


def build(
    glosses: list[Gloss],
    *,
    mother_lang: str = SOURCE_LANG,
    model: str | None = None,
    host: str | None = None,
    translate: bool = True,
    refresh_answers: bool = False,
) -> list[Card]:
    """Turn definition fetching's output into the design's list of cards."""
    translator = Translator(
        mother_lang=mother_lang,
        model=model or default_model(),
        host=host,
        enabled=translate,
        refresh=refresh_answers,
    )
    builder = _Builder()
    #: For each gloss decker titles itself, the title it would have had
    #: untranslated -- kept for :func:`_unclashed`, which needs it only if the
    #: translation turns out not to tell two cards apart.
    english: dict[int, str] = {}
    #: The scripts the reader already reads, for the masking in `_asked`:
    #: whether a term quoted inside its own definition is quoted in a writing
    #: system the reader can follow decides how far the mask goes. ``None``
    #: where decker does not know the mother tongue's scripts, which is the
    #: cautious answer and the one `--teach-script` stands down on.
    reads = script.scripts_of(mother_lang)
    #: The third long stage, and the third that degrades rather than fails:
    #: a card whose translation was skipped keeps the edition's language, which
    #: is what a run without a model does anyway, and the translator's report
    #: says how many did.
    with console.phase("cards", len(glosses), unit="glosses"):
        for gloss in glosses:
            if console.skipping():
                translator.enabled = False
            definition, examples, etymology = translator.gloss(
                definition=gloss.definition,
                examples=gloss.examples,
                etymology=gloss.etymology,
                target_language=gloss.language,
            )
            #: After the translation, not instead of it: `gloss` renders the
            #: examples the edition rendered, and this one writes a rendering
            #: for the examples it left bare. A deck in the edition's own
            #: language has nothing to do here.
            examples = translator.rendered(examples, target_language=gloss.language)
            title = _titled(gloss, definition, translator)
            if title != gloss.surface:
                english[gloss.index] = _fronted(gloss, gloss.surface, definition)
            _pair(
                builder,
                gloss,
                title,
                definition,
                examples,
                etymology,
                reads,
                _equivalent(gloss, translator),
            )
            console.advance(items=0)
    translator.report()
    cards = _unclashed(builder.cards, english)
    log(f"[decker] {len(cards)} cards", kind="head")
    return cards


def _titled(gloss: Gloss, definition: str, translator: Translator) -> str:
    """The card's title, with decker's own prose in the mother language.

    Only two kinds of gloss have any: a concept and a rule are titled by
    decker out of the English glossary and the English inflection line, and
    everything else is titled with the language itself -- a word by
    Wiktionary's spelling of it, a symbol by the character. So a gloss with no
    `title_prose` is handed back untouched, which is every gloss in the usual
    run and every gloss at all in a deck whose mother tongue is the edition's.

    The translated prose is put back into `surface` rather than a title being
    built up from its parts, so that whatever else the title holds survives in
    the place it was written: `Rule: comparative form (older)` keeps `(older)`
    where it was, and keeps it in English, because `older` is the word being
    taught. The gloss is not touched -- `gloss.surface` is what `gloss_key`,
    `--previous` and the rule book see, and a deck that renamed its own cards
    per mother tongue would stop recognising the decks before it.
    """
    if not gloss.title_prose:
        return gloss.surface
    written = f"{gloss.title_prefix}{gloss.title_prose}"
    return gloss.surface.replace(
        written,
        translator.title(
            prefix=gloss.title_prefix,
            prose=gloss.title_prose,
            target_language=gloss.language,
        ),
        1,
    )


def _equivalent(gloss: Gloss, translator: Translator) -> str:
    """The mother tongue's word for this sense, where the deck has to ask.

    Every other deck gets it for nothing. A Spanish deck for an English
    speaker reads `todavía`'s entry in the English Wiktionary and the entry
    says *still*: the edition is written in the mother tongue, so its
    definitions already are the translation. Turn the pair around -- English
    taught to a Spanish speaker -- and the edition is written in the language
    being taught, so `still`'s entry describes the word instead: *up to a
    given time, as in the preceding time*. Translating that gives a Spanish
    speaker a Spanish paraphrase of an English idea and never the word
    `todavía`, which is the one thing they were after. So it is asked for,
    and the card shows it above the description rather than instead of it:
    the description is what tells this sense of `still` from the others, and
    the word is what the sense is worth knowing for. Bru's call, 2026-09-19.

    Only the glosses that teach a word. A concept and a rule are decker's own
    cards about grammar, whose titles are not words of any language to have an
    equivalent of, and a symbol is a character rather than a word -- all three
    are the glosses decker titles itself, which is what `title_prefix` marks.
    """
    if gloss.title_prefix or gloss.language != SOURCE_LANGUAGE:
        return ""
    return translator.equivalent(
        term=gloss.surface,
        definition=gloss.definition,
        target_language=gloss.language,
    )


def _unclashed(cards: list[Card], english: dict[int, str]) -> list[Card]:
    """Cards a translation left with one title between them, told apart again.

    A title decker writes is what says which card of its kind this is, which
    is why a symbol card carries a prefix at all and why a rule's title
    carries its representative. A translation can take that away: asked for
    `archaic` and for `obsolete`, gemma3:4b answered `arcaico` to both, and
    two cards stood in the deck with one front and two different backs -- the
    one thing the titling exists to prevent. It happened in each of the two
    sweeps made over one deck's 47 glossary names, on a different pair each
    time.

    So a title that ends up standing for more than one card is refused, and
    every card that landed on it goes back to the English that did tell them
    apart. Both of them, not the second: one card reading `Concepto: arcaico`
    and another `Concept: obsolete` would look like two unrelated cards rather
    than the pair they are. The model is the variable here -- a bigger one
    collides less -- so this is a net under the answer and not a judgement of
    it, and the run says how often it caught something.
    """
    if not english:
        return cards
    on = defaultdict(set)
    for card in cards:
        if card.gloss in english and card.challenge.term:
            on[card.challenge.term].add(english[card.gloss])
    clashing = {title for title, was in on.items() if len(was) > 1}
    if not clashing:
        return cards
    log(
        f"[decker] {len(clashing)} translated titles stood for more than one "
        f"card and kept their {SOURCE_LANGUAGE}",
        kind="warn",
    )
    #: Not under `card.`, which the screen adds up to say how many cards the
    #: deck holds: a clash is not a card.
    count("title.clash", len(clashing))
    return [
        replace(
            card,
            challenge=replace(card.challenge, term=english[card.gloss]),
        )
        if card.gloss in english and card.challenge.term in clashing
        else card
        for card in cards
    ]


def _fronted(gloss: Gloss, title: str, definition: str) -> str:
    """The term as the front of its recognition card says it.

    The word, and -- where the sense it teaches is a figure of the word --
    the label the dictionary marks it with: `мрак (poetic)` against `мрак`.
    Both cards exist because a marked sense now drags its plain sense into the
    deck (`docs/execution/definition-fetching.md`), and without the label the
    learner meets the same front twice and has to guess which of the two
    answers is wanted. The label is the question narrowing, not the answer
    leaking: it says which register is being asked for and not what the word
    means there. Bru's call, 2026-09-17.

    Read off the translated definition, so a deck in another mother tongue
    shows the label its back shows, and off Wiktionary's own where the
    translation dropped the parenthesis. Presentation only: the gloss keeps
    its spelling, so `gloss_key`, the rules stage and `--previous` all see
    what they saw before.
    """
    if not is_marked(gloss.definition):
        return title
    label = leading_qualifier(definition) or leading_qualifier(gloss.definition)
    return f"{title} {label}" if label else title


def _asked(
    gloss: Gloss, definition: str, answer: str, reads: tuple[str, ...] | None
) -> str:
    """The question on a production card: the meaning, and which card it is.

    A definition that spells its own term out asks nothing -- `分かる, 解る:
    to be understandable` is a card answering itself -- so the answer is
    masked out of the question either way. What differs is how much of it
    counts: a symbol is masked piece by piece (:func:`_hidden`), a word whole
    -- wherever it stands when the reader could not have read it anyway, and
    where Wiktionary marks the definition as quoting it when they could
    (:func:`_unspelled`). The prefix decker titles a symbol card with moves
    here as well, in front of the masked prose.
    """
    if gloss.title_prefix:
        return f"{gloss.title_prefix}{_hidden(definition, answer)}"
    return _unspelled(definition, answer, reads, gloss.quoted)


def _unspelled(
    definition: str,
    answer: str,
    reads: tuple[str, ...] | None,
    quoted: tuple[str, ...] = (),
) -> str:
    """``definition`` with the term itself blanked out of it.

    The whole term and nothing shorter, which is what separates this from
    :func:`_hidden`: the letters of `casa` blanked out of *house* would take
    the house with it. 75 of the Gokurakugai deck's word cards printed their
    own answer -- `short for 金玉 (kintama): testicles` asked for 玉 -- and
    each is now `short for 金■ (kintama)`. Bru's call, 2026-09-18.

    **A term the reader cannot read** is masked wherever it stands, which is
    the same test `--teach-script` runs and the same table behind it:
    :func:`decker.script.foreign` against the scripts
    :func:`decker.script.scripts_of` gives the mother tongue. One character
    of another script is enough, since the match then carries that character
    and cannot land inside the mother tongue's own prose -- which is why this
    half may replace blindly, 玉 inside 金玉 included.

    **A term in the reader's own script is masked only where Wiktionary says
    the definition is quoting it**: `gloss.quoted`, read from the wiki's own
    self-link markup (:func:`decker.pages._quoted_in`). Guessing from the
    letters cannot work here and the deck paid for every guess: a Japanese
    romaji card lost the romanization it was teaching -- `The hiragana
    syllable あ (■)` for `a` -- German `in`, defined *in, into*, came out as
    `■, into`, and `Seine` is *■ (a river in France)*. Requiring the
    occurrence to stand alone as a word saved none of them, because the
    collision is real: the mother tongue has those words too. The wiki draws
    the line decker cannot, because the English `nice` in German `nice`'s
    definition *good, nice* is a link to the page's **English** section and
    the German `müssen` in *“müssen” replaces the past participle* is a link
    to the page itself. Bru's call, 2026-09-20.

    Only where it stands as a word of its own, for this half. The answer is
    spelled in the mother tongue's alphabet here, so a blind replacement
    takes the `e` out of every word on the card: `e`'s own definition, *The
    name of the Latin script letter E/e*, becomes `Th■ nam■ of th■ Latin
    script l■tt■r E/■`.

    ``reads`` is ``None`` when decker does not know which scripts the mother
    tongue uses; the script half stands down then, as `--teach-script` does
    on the same unknown, and the quotation half is unaffected -- it never
    asked what the reader can read.
    """
    if not answer:
        return definition
    foreign = reads is not None and bool(script.foreign(answer, reads))
    spellings = [answer] if foreign else []
    spellings += [
        one for one in _quotations(quoted, answer) if one not in spellings
    ]
    for spelling in spellings:
        #: Blindly where the script itself is the guarantee, and only where
        #: the word stands on its own where it is not.
        definition = (
            definition.replace(spelling, MASK)
            if foreign
            else _standing(definition, spelling)
        )
    return definition


#: A word character in any script, for the boundaries :func:`_standing` puts
#: around a term it masks.
_WORD = re.compile(r"\w")


def _standing(definition: str, term: str) -> str:
    """``definition`` with ``term`` masked wherever it stands as a word.

    A boundary on each side the term has a letter on, and none on a side it
    does not: `des-` is masked before a space and before its own hyphen
    alike, and a term of punctuation is matched as it falls.
    """
    left = r"(?<!\w)" if _WORD.match(term[0]) else ""
    right = r"(?!\w)" if _WORD.match(term[-1]) else ""
    return re.sub(left + re.escape(term) + right, MASK, definition)


def _quotations(quoted: tuple[str, ...], answer: str) -> tuple[str, ...]:
    """Which of ``quoted`` are the answer, as the definition spells them.

    The page quotes its own word as the *page* writes it, which is not always
    how the title does: a mention carries more marks than an entry is titled
    with, so Russian `русский` is quoted `ру́сский` and an exact comparison
    misses the one card it matters on. So a quotation also counts as the
    answer when taking its combining marks off leaves the answer exactly --
    and what comes back is the quotation, since that is the spelling standing
    in the prose.

    Composed first, and only what will not compose is taken off. That is the
    difference between a mark the wiki adds and a mark the alphabet has: the
    stress on `ру́сский` is a combining acute with no letter of its own to
    become, while `й` is one character and `á` is one character, so both
    survive. Decomposing instead had turned `ру́сский` into `русскии` and
    matched nothing.

    Stripped on the quotation's side only, never the answer's, so this can
    only ever recover the answer's own spelling: Spanish `papá` is not masked
    by a definition that quotes `papa`, which is a different word.
    """
    found = []
    for one in quoted:
        bare = "".join(
            piece
            for piece in unicodedata.normalize("NFC", one)
            if not unicodedata.combining(piece)
        )
        if one == answer or bare == answer:
            found.append(one)
    return tuple(found)


def _hidden(definition: str, answer: str) -> str:
    """``definition`` with every piece of ``answer`` blanked out.

    A symbol's definition is usually written *around* the character --
    "the hiragana syllable る (ru)", "the fifth letter of the Russian
    alphabet, called дэ" -- and that sentence is the whole question its
    production card asks. Printed as it stands it answers itself: 102 of the
    Gokurakugai deck's 487 symbols showed the learner the character they were
    being asked to write. So each piece of the answer is replaced by
    :data:`MASK`: `the hiragana syllable ■ (ru)`, which asks exactly what the
    card is for.

    *Piece*, not *character*, because the answer may be more than one code
    point -- a combining mark is shown on its carrier, `◌ָ` -- and a
    definition may quote either the pair or the mark alone. The whole form
    goes first so the pair becomes one square rather than two.

    Nothing else is masked, and the restraint is the point: `ル`'s definition
    says *its equivalent in hiragana is る*, and る is a different shape with
    a card of its own. Blanking every character that merely resembles the
    answer -- the other case of a letter, the kana of the other syllabary --
    would blank the deck's own other cards out of the prose that explains
    them. Case in particular stays: `Д` is *called дэ*, and `д` is a card the
    reader has already met.
    """
    for piece in (answer, *answer):
        if piece:
            definition = definition.replace(piece, MASK)
    return definition


def _pair(
    builder: _Builder,
    gloss: Gloss,
    title: str,
    definition: str,
    examples: tuple[Example, ...],
    etymology: str | None,
    reads: tuple[str, ...] | None = None,
    equivalent: str = "",
) -> None:
    """The recognition and production cards of one gloss, in that order."""
    recognition = builder.add(
        kind=RECOGNITION,
        gloss=gloss.index,
        key=gloss.key,
        entry=gloss.entry,
        language=gloss.language,
        anchor=gloss.anchor,
        attribution=gloss.attribution,
        challenge=Side(
            term=_fronted(gloss, title, definition), examples=_unrendered(examples)
        ),
        #: The sound file rides with the reading: both answer the same
        #: question, and the run has already downloaded it.
        answer=Side(
            definition=definition,
            equivalent=equivalent,
            renderings=_renderings(examples),
            ipa=gloss.ipa,
            readings=gloss.readings,
            etymology=etymology,
            audios=gloss.audios,
            headword=gloss.headword,
        ),
        depends_on=_after(builder, gloss),
    )
    builder.introduced_by[gloss.index] = recognition
    count(f"card.{RECOGNITION}")
    if not gloss.production:
        #: A concept or a rule gets the recognition card alone. The production
        #: card asks for the term given the meaning, and their term is the name
        #: of the card itself -- "produce `Concept: dative case` from its
        #: description" is a question about decker's own titling, not about
        #: the language being learned. Bru's call, extended to rules, whose
        #: titles decker writes just as much. A symbol's title is not decker's
        #: prose but the character itself, so it is not in this company.
        return
    count(f"card.{PRODUCTION}")
    #: What the learner has to write, and so what the question must not
    #: show: the character alone for a symbol, decker's label taken off.
    answer = gloss.surface.removeprefix(gloss.title_prefix)
    builder.add(
        kind=PRODUCTION,
        gloss=gloss.index,
        key=gloss.key,
        entry=gloss.entry,
        language=gloss.language,
        anchor=gloss.anchor,
        attribution=gloss.attribution,
        #: The title's prefix moves to the question: `Symbol: drink` asks
        #: for 飲 where a bare `drink` would leave the learner guessing
        #: whether the character or 飲む is wanted, the two being different
        #: cards in the same deck. The same narrowing `_fronted` does on a
        #: marked sense, and by the same rule -- it says which answer is
        #: being asked for, not what it is. The definition itself is masked
        #: where it spells the answer out, which is the one way this question
        #: could say what it is -- a symbol piece by piece, a word where the
        #: whole term stands. Presentation only, so the gloss, its key and
        #: `--previous` see the prose Wiktionary wrote.
        #: The equivalent is on this side too, and above the description
        #: here as well: this question asks for the word given the meaning,
        #: and `todavía` is the meaning said in one word. It cannot leak the
        #: answer -- it is the answer's translation, in another language --
        #: and the one shape that could, the model handing `still` back for
        #: `still`, is refused where the answer is asked for.
        challenge=Side(
            definition=_asked(gloss, definition, answer, reads),
            equivalent=equivalent,
        ),
        #: The recording is on this answer too, and for the same reason it is
        #: on the other one: the answer here *is* the word, and how the word
        #: sounds is part of producing it. The file is already downloaded and
        #: already in the package, so the second card costs a field and no
        #: bytes. Bru's call, 2026-09-18.
        answer=Side(
            #: The character alone: what the learner has to write is 飲, and
            #: `Symbol: ` is decker's word for which pile the card is in,
            #: which the question has just said.
            term=answer,
            ipa=gloss.ipa,
            readings=gloss.readings,
            etymology=etymology,
            audios=gloss.audios,
            headword=gloss.headword,
        ),
        #: Its own recognition card, and nothing else: whatever the gloss
        #: depends on is already behind that card, and the ordering the
        #: design asks for is transitive.
        depends_on=(recognition,),
    )


def _unrendered(examples: tuple[Example, ...]) -> tuple[Example, ...]:
    """The examples as the question shows them: sentences alone."""
    return tuple(replace(example, rendering=None) for example in examples)


def _renderings(examples: tuple[Example, ...]) -> tuple[str, ...]:
    """The renderings of those sentences, in the same order.

    Only the ones there are: an example Wiktionary carries no rendering for
    contributes nothing here rather than an empty line, and the answer side of
    a gloss whose examples are all unrendered has no renderings at all.
    """
    return tuple(
        example.rendering for example in examples if example.rendering
    )


def _after(builder: _Builder, gloss: Gloss) -> tuple[int, ...]:
    """The cards a gloss's own card must follow.

    A gloss depends on the word its definition describes it in terms of --
    `patita` on `pata` -- and what that dependency asks is that the reader
    have met the word, which is what the recognition card is. Being able to
    produce `pata` on demand is a further thing, and not one `patita` needs.
    """
    return tuple(
        builder.introduced_by[index]
        for index in gloss.depends_on
        if index in builder.introduced_by
    )

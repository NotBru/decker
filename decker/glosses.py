"""Definition fetching: from terms to glosses.

One gloss per term, plus one for the lemma whenever the term is inflected and
Wiktionary spells the lemma under a page of its own. The inflected gloss
depends on the lemma's, and its definition is the form-of line Wiktionary
already writes -- "third-person singular preterite indicative of correr" --
which is exactly the relationship the design asks the inflected gloss to
explain. Glosses appear in the order their terms occur in the source, a
dependency always before what depends on it.

Three kinds of gloss are not a word of the text: a concept, read from
`Appendix:Glossary` for the terminology a definition is written in; a
morphological rule, worked out in :mod:`decker.morphology` from the form-of
line itself; and, under `--teach-script`, a symbol -- one character of a term,
written in a script the reader does not have. The first two explain the
machinery a definition uses rather than a word the reader met; the third is
what a word is spelled with. The first two carry no production pair; a
symbol does, since producing a character from what it says is a question about
the writing system and not about decker's titling.
"""

from __future__ import annotations

import dataclasses
import hashlib
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from decker import pages, script
from decker.console import DETAIL, VERBOSE, console, count, log
from decker.disambiguation import Disambiguator
from decker.languages import name_of, section_of
from decker.morphology import RULE_PREFIX, Morphology, Outcome, Rule, label_of
from decker.ollama import default_model
from decker.pages import Concept, Entry, Example, Page, Sense
from decker.terms import Term
from decker.unknown import ATTRIBUTION as UNKNOWN_ATTRIBUTION
from decker.unknown import Unknowns

if TYPE_CHECKING:
    from decker.pipeline import SentenceTerms


#: What a concept card is called. The design names the form -- the concept is
#: not a word of the language being learned, and a card titled `dative` among
#: cards titled with Spanish words would read as one.
CONCEPT_PREFIX = "Concept: "

#: What a rule card says about where its text came from. Every other card's
#: prose is Wiktionary's, quoted under CC BY-SA, and the card credits it; a
#: rule is written by the model out of Wiktionary's inflection line, which is
#: a different claim and has to read as one.
RULE_ATTRIBUTION = (
    "Rule written by {model} from Wiktionary's inflection line, not quoted "
    "from it."
)

#: What a symbol card is called. The same reason the concept cards carry a
#: prefix, and one more: without it a Chinese deck would hold two cards
#: fronted by `水`, the character and the word, and nothing on either to say
#: which question is being asked.
SYMBOL_PREFIX = "Symbol: "

#: What a symbol card says when Wiktionary documents the character nowhere
#: decker can reach and the Unicode name is all there is: `한` is a Hangul
#: syllable block, and the English Wiktionary writes the alphabet one jamo at
#: a time. A different claim from a quotation, so it reads as one, exactly as
#: a rule's does.
SYMBOL_ATTRIBUTION = (
    "Named from the Unicode character database; the English Wiktionary has no "
    "entry for this character."
)

#: The parts of speech under which a page talks about the character as a piece
#: of writing, most telling first. `ж` heads a Russian Letter, a Particle and
#: a Noun, and only the first is what a symbol card is for. Word parts of
#: speech stay out, with the one exception noted below: Korean `한` heads a
#: Numeral, a Determiner and four more, and *one (as a determiner numeral)* is
#: a card about a word that happens to be one syllable, not about the
#: syllable.
SHAPE_PARTS = (
    "Letter",
    "Letters",
    #: Before `Syllable`, which a Han character can also head: `子` is the
    #: kanji for *child* and, further down the same section, an obsolete
    #: man'yōgana spelling of the katakana ネ. The kanji is the card.
    "Kanji",
    "Hanzi",
    "Hanja",
    "Han character",
    "Syllable",
    "Character",
    "Punctuation mark",
    "Diacritical mark",
    #: How the English Wiktionary heads a Chinese entry that pools its parts
    #: of speech, and the only place a Han character's meaning is written:
    #: 的 has no Translingual section at all, and without this its card would
    #: read `CJK UNIFIED IDEOGRAPH-7684`. For a character the meaning *is* the
    #: shape's, which is how the script is learned; and where the text uses
    #: the character as a word of its own, that word's gloss answers first and
    #: no symbol card is made.
    "Definitions",
    #: And how it heads a mark that attaches to what precedes it: Japanese
    #: ー is a Combining form, *the long-vowel mark*, and nothing else.
    "Combining form",
)

#: And the part of speech under which the character is a piece of *notation*
#: rather than a piece of writing. A page's own language section may answer
#: with one -- Japanese `々` is a Symbol there, and it is the right answer --
#: but the Translingual section may not: its `¡` is an extIPA percussive,
#: which would be a false card for a term that merely contains the glyph.
NOTATION_PARTS = ("Symbol",)

#: The languages whose sections write what a Han character *means*, asked in
#: this order and asked last: after the target language has been asked about
#: the character and about the words written with it alone, and before the
#: Unicode name. Chinese is where the English Wiktionary writes a character's
#: meaning out, under `Definitions`; Korean and Vietnamese answer for a few it
#: has dropped.
#:
#: Last, and not first, because a Han character's meaning is *not* the same in
#: every language that took it, which is the thing this stage got wrong on
#: 2026-09-19 and a run caught the same hour: 娘 is *mother* in Chinese and
#: *daughter* in Japanese, 靴 is a boot there and a shoe here. A borrowed
#: character carries a borrowed meaning, and the meaning drifted. So the
#: target language answers about its own writing wherever it says anything at
#: all, and this is for the character it has no section for. And only for Han,
#: which is the one script decker teaches whose characters mean anything.
HAN_SOURCES = ("zh", "ko", "vi")

#: The section a character's own entry lives under when no language claims it:
#: the IPA symbols, the punctuation and the Han characters are all written
#: here, and it is a heading like any other as far as :mod:`decker.pages` is
#: concerned.
TRANSLINGUAL = "Translingual"


def gloss_key(surface: str, definition: str) -> str:
    """A gloss's identity, as a string that survives leaving the process.

    The design identifies a gloss by its inflected form and its sense, which
    is what `_Builder.seen` already keys on. This is the same pair, hashed, so
    it can be written into a deck and read back out of one: the definition it
    hashes is Wiktionary's own, never the translated text, so a deck built for
    a speaker of Spanish and one built for a speaker of German agree about
    which glosses they teach.
    """
    digest = hashlib.sha256(f"{surface}\n{definition}".encode())
    return digest.hexdigest()[:16]


@dataclass(frozen=True)
class Gloss:
    """One thing to be learned, ready for cards to be built from it."""

    #: Position in the list, increasing with occurrence in the source.
    index: int
    #: The form the term takes in the text.
    surface: str
    #: The lemmatized form of the term.
    lemma: str
    #: The Wiktionary page the data below was read from.
    entry: str
    #: The one sense this gloss teaches. A page's surviving senses become one
    #: gloss apiece, which is the design's identity for a gloss and what lets
    #: the same sense met twice collapse.
    definition: str
    #: The language section the data was read from, as Wiktionary names it.
    language: str = ""
    examples: tuple[Example, ...] = ()
    etymology: str | None = None
    ipa: tuple[str, ...] = ()
    #: Wiktionary's sound file for the entry, if it has one. Kept whether or
    #: not the file itself was downloaded: a document wants the link.
    audio_urls: tuple[str, ...] = ()
    #: Cached sound files, for whichever of the above were downloaded.
    audios: tuple[str, ...] = ()
    #: Indexes of the glosses this one depends upon.
    depends_on: tuple[int, ...] = ()
    #: :func:`gloss_key` of this gloss, carried so a deck can record it.
    key: str = ""
    #: Index of the sentence this gloss was first made for. A gloss is made
    #: once, at its first occurrence, so this is where the reader first meets
    #: it -- and for a concept or a rule, the first sentence that needed it.
    #: -1 for a gloss made outside the walk over the sentences.
    first_sentence: int = -1
    #: For a concept read from `Appendix:Glossary`, where on that page it
    #: lives. Empty for an ordinary gloss, whose entry is a word and whose
    #: link goes to its language section instead.
    anchor: str = ""
    #: Whether deck construction makes the production card as well. The design
    #: withholds the pair from the glosses whose title decker writes: asking
    #: for `Concept: dative case` or for a rule's title, given its explanation,
    #: is a question about decker's own titling and not about the language. A
    #: symbol is the exception among the three -- its title is a character the
    #: reader has to be able to write -- and keeps the pair.
    production: bool = True
    #: Where this gloss's prose comes from, when it is not Wiktionary's. Only
    #: a rule has one: its text is the model's, written from an entry rather
    #: than quoted from it, and a card crediting Wiktionary for it would be
    #: saying something false about a licence.
    attribution: str = ""
    #: How Wiktionary announces the word: its gender and its paradigm, as
    #: `f (plural servilletas)`. Bru's call, 2026-09-14: it goes on the
    #: answers, on whichever word the page states it for, and it culls
    #: nothing -- an inflected form of the text still gets its own card.
    #: Empty for a concept, a rule, and for a form that announces only itself.
    headword: str = ""
    #: The prefix decker puts on this gloss's title, when it writes one --
    #: `Symbol: `, `Concept: `, `Rule: `, and nothing for a word, whose title
    #: is Wiktionary's. It is part of `surface`, and named separately because
    #: the production card has to take it off the answer and put it on the
    #: question: what the learner writes is the character alone, and what the
    #: question has to say is that a character is what it wants.
    title_prefix: str = ""
    #: The spellings of this word that its own definition quotes, as
    #: Wiktionary's self-link markup names them -- see
    #: :func:`decker.pages._quoted_in`. Read for the production card, whose
    #: question is the definition and whose answer is the word: `(auxiliary,
    #: with an infinitive → “müssen” replaces the past participle)` prints its
    #: own answer. Empty for a definition that does not name its word, which
    #: is nearly all of them.
    quoted: tuple[str, ...] = ()
    #: The part of that title which is decker's prose rather than a word of
    #: the language: a concept's name, a rule's feature bundle. Deck
    #: construction translates it and leaves the rest of `surface` alone --
    #: a symbol's character, a rule's representative word -- so this is empty
    #: for a symbol and for a word, whose titles are nothing but the language.
    #: `surface` itself keeps the English, because `gloss_key`, `--previous`
    #: and the rule book are all written against it.
    title_prose: str = ""


@dataclass
class _Builder:
    """Accumulates glosses, keeping them unique and ordered."""

    edition: str
    lang: str
    disambiguator: Disambiguator
    morphology: Morphology
    audio: bool = True
    refresh: bool = False
    glosses: list[Gloss] = field(default_factory=list)
    #: Inflected form and sense, the design's identity for a gloss.
    seen: dict[tuple[str, str], int] = field(default_factory=dict)
    #: Which sentence is being glossed, so every gloss made while it is --
    #: the word itself, a concept its definition names, the rule behind its
    #: form -- records where the reader first meets it. Set by :func:`build`
    #: as it walks the sentences, because only the walk knows.
    position: int = -1
    #: Pages already looked up this run, misses included.
    fetched: dict[str, Page | None] = field(default_factory=dict)
    #: Per page, which of its definitions describe it in terms of what.
    refs: dict[str, dict[str, tuple[str, ...]]] = field(default_factory=dict)
    #: How many recordings the pages offered, so a run that ends with none
    #: can say why instead of looking like every word simply has no audio.
    offered: int = 0
    #: Pages whose source has no media at all, by title. Their silence is the
    #: source's, not the word's, and a mixed run cannot tell the two apart
    #: from the cards.
    silent: set[str] = field(default_factory=set)
    #: Glosses a previously built deck already teaches, by key.
    known: frozenset[str] = frozenset()
    #: How many were dropped for being in it.
    skipped: int = 0
    #: Whether the terminology inside a definition becomes cards of its own.
    concepts: bool = True
    #: Whether the terms an etymology decomposes a word into become cards of
    #: their own, recursively, the way a form-of's target does.
    components: bool = True
    #: The titles glossed because an etymology named them as a component,
    #: counted for the run's tally. Distinct titles, and only those that had
    #: no card under that spelling already.
    composed: set[str] = field(default_factory=set)
    #: `Appendix:Glossary`, by every anchor that reaches an entry of it. One
    #: page, read on first use, so a run that glosses nothing never asks for it.
    _glossary: dict[str, Concept] | None = None
    #: Anchors linked by a definition that the glossary has no entry for.
    unresolved: Counter[str] = field(default_factory=Counter)
    #: How many of the glosses below are concepts rather than words.
    concept_count: int = 0
    #: How many are morphological rules.
    rule_count: int = 0
    #: What becomes of the terms Wiktionary has no entry for.
    unknowns: Unknowns | None = None
    #: How many of those were taught anyway, as foreign words.
    foreign_count: int = 0
    #: Whether the characters of a term have to have been taught before it.
    teach_script: bool = False
    #: The scripts the reader already reads, from their mother tongue.
    reads: tuple[str, ...] = ()
    #: Characters already dealt with, to the gloss that teaches them: an index,
    #: or ``None`` where there is nothing to depend on -- a previous deck
    #: taught it, or the character could not be resolved at all.
    symbols: dict[str, int | None] = field(default_factory=dict)
    #: How many of the glosses are symbols.
    symbol_count: int = 0
    #: Every gloss by the form it teaches, for the one question `seen` cannot
    #: answer: whether *this character* has a card already, whatever sense it
    #: was taught in. A Chinese text teaches 水 as a word the first time it
    #: uses it, and the character wants no second card after that.
    by_surface: dict[str, int] = field(default_factory=dict)
    #: Pages read under :data:`TRANSLINGUAL` rather than under the target
    #: language, kept apart from `fetched` because they are the same titles
    #: cut to a different section.
    translingual: dict[str, Page | None] = field(default_factory=dict)
    #: And pages read under one of :data:`HAN_SOURCES`, by title and language,
    #: for the same reason: the same title cut to a third section again.
    borrowed: dict[tuple[str, str], Page | None] = field(default_factory=dict)

    def glossary(self) -> dict[str, Concept]:
        if self._glossary is None:
            self._glossary = pages.glossary(self.edition, refresh=self.refresh)
        return self._glossary

    def references_of(self, page: Page) -> dict[str, tuple[str, ...]]:
        if page.title not in self.refs:
            self.refs[page.title] = references(page)
        return self.refs[page.title]

    def page(self, title: str) -> Page | None:
        if title not in self.fetched:
            log("fetching", word=title, level=DETAIL, kind="detail")
            self.fetched[title] = pages.fetch(
                title, edition=self.edition, lang=self.lang, refresh=self.refresh
            )
            #: The outcome rather than the request: a page that came back
            #: without a section in this language is the ordinary reason a word
            #: of the text gets no card, and at `-v` it is the line worth
            #: seeing. The fetch itself is one level further down.
            page = self.fetched[title]
            if page is None:
                log(f"no {name_of(self.lang)} section", word=title,
                    level=VERBOSE, kind="missing")
            else:
                log(
                    f"{len(page.senses)} sense"
                    f"{'' if len(page.senses) == 1 else 's'}"
                    f"{' from ' + page.source if page.source else ''}",
                    word=title, level=VERBOSE, kind="found",
                )
        return self.fetched[title]

    def first_page(self, titles: tuple[str, ...]) -> Page | None:
        """The first of a term's entries that has a section in the language."""
        for title in titles:
            page = self.page(title)
            if page is not None:
                return page
        return None

    def own_pages(self, term: Term) -> list[Page]:
        """The pages of the term's own spellings, capital and lower case both.

        `Bueno` reaches a surname and `bueno` an adjective; which the sentence
        means is a question about sense, so both pages are returned and their
        definitions are pooled into one choice.
        """
        spellings = set(term.spellings)
        return [
            page
            for title in term.entries
            if title in spellings and (page := self.page(title)) is not None
        ]

    def add(
        self,
        page: Page,
        *,
        surface: str,
        lemma: str,
        sense: Sense,
        depends_on: tuple[int, ...] = (),
    ) -> int | None:
        """Append a gloss, or the index of one already standing, or nothing.

        Nothing when a previously built deck already teaches it: the design
        has such glosses leave the pipeline here, at definition fetching, and
        a caller that was going to depend on this one simply does not.
        """
        key = (surface, sense.definition)
        if key in self.seen:
            return self.seen[key]
        if gloss_key(surface, sense.definition) in self.known:
            self.skipped += 1
            count("gloss.known")
            return None
        #: Before the gloss itself, so a concept it names is already standing
        #: and carries the lower index: the terminology inside a definition is
        #: something to be met before the definition that uses it, which is
        #: exactly what a dependency says. The characters of the term go in
        #: front of both: a card the reader cannot read is not improved by
        #: their knowing what dative means.
        depends_on = _merge(
            depends_on,
            #: With the term's own reading, which is what tells a character
            #: met in 靴下 from the same character met in 地下: see
            #: `_as_read`.
            self.symbols_in(surface, page.ipa_of(sense)),
            self.concepts_of(sense),
        )
        index = len(self.glosses)
        self.glosses.append(
            Gloss(
                index=index,
                first_sentence=self.position,
                surface=surface,
                lemma=lemma,
                entry=page.title,
                definition=sense.definition,
                language=page.language,
                examples=sense.examples,
                #: The etymology of this sense's own block, which is the
                #: section's only where the page numbers just one.
                etymology=page.etymology_of(sense),
                headword=page.headword_of(sense),
                quoted=sense.quoted,
                #: And the pronunciation of that same block, for the same
                #: reason: Russian `в` is a letter, a preposition and an
                #: abbreviation of `вольт` under three numbered etymologies,
                #: each with its own Pronunciation, and the preposition's card
                #: was carrying all three -- `[v] [vʲ] [f] [vɛ] [v] [f] [və]
                #: [volʲt]` -- and all three recordings with them.
                ipa=page.ipa_of(sense),
                audio_urls=(recordings := page.audio_of(sense)),
                audios=self._audios(page, recordings),
                depends_on=depends_on,
                key=gloss_key(surface, sense.definition),
            )
        )
        self.seen[key] = index
        self.by_surface.setdefault(surface, index)
        count("gloss.word")
        return index

    def symbols_in(
        self, term: str, readings: tuple[str, ...] = ()
    ) -> tuple[int, ...]:
        """Gloss every character of ``term`` written in a script new to them.

        **The term, and nothing else on the card.** Bru's call of 2026-09-16,
        narrowing this stage the day it was written: not the definition, not
        the readings, not the examples. What a learner has to be able to read
        is the word they are being taught, and a deck that stopped to teach
        the Greek of an etymology and the symbols of a transcription taught
        neither the word nor the script.
        """
        if not self.teach_script:
            return ()
        found = [
            self.symbol(character, readings)
            for character in script.foreign(term, self.reads)
        ]
        return tuple(index for index in found if index is not None)

    def symbol(
        self, character: str, readings: tuple[str, ...] = ()
    ) -> int | None:
        """The gloss that teaches one character, making it if there is none.

        A character the text already teaches as a word of its own is that
        word's gloss: the reader has met the shape, which is all a dependency
        here asserts. It is what keeps a Chinese deck from carrying a symbol
        card behind every word card.

        Including the word being glossed at this moment, which is the half
        the rule was missing: `決` asked for its own character while its own
        gloss was still being built, found nothing in `by_surface` and made
        `Symbol: 決` a card ahead of an identical `決`. A term is not taught
        before itself, so there is nothing to depend on and nothing to teach.
        """
        if character in self.symbols:
            return self.symbols[character]
        if (word := self.by_surface.get(character)) is not None:
            self.symbols[character] = word
            return word
        index = self._teach(character, readings)
        self.symbols[character] = index
        return index

    def _teach(
        self, character: str, readings: tuple[str, ...] = ()
    ) -> int | None:
        """Append the gloss for one character.

        Wiktionary first, as everything else here is: the target language's
        own section when it has one -- `ж` is *the eighth letter of the
        Russian alphabet*, with `[ʐ]` and a recording, `あ` is *the hiragana
        syllable* -- and :data:`TRANSLINGUAL` when it does not, which is where
        the Han characters are written. Only the parts of speech in
        :data:`SHAPE_PARTS` and :data:`NOTATION_PARTS`: a page is asked about
        the shape, and the word that happens to be spelled with it is a
        different card that the text will ask for itself if it uses it.
        """
        entry, sense, speaks = self._symbol_entry(character, readings)
        shown = script.displayed(character)
        surface = f"{SYMBOL_PREFIX}{shown}"
        definition = sense.definition if sense else script.unicode_name(character)
        key = (surface, definition)
        if key in self.seen:
            return self.seen[key]
        if gloss_key(*key) in self.known:
            self.skipped += 1
            return None
        page = entry[0] if entry else None
        #: A reading only where the block that answered is the character's
        #: own. Where it is not, the card carries none and is right to: a
        #: kanji has no pronunciation, only the words written with it do, and
        #: 下 is *shita*, *shimo*, *moto*, *ge* and *ka* by turns. Putting one
        #: of them on the character's card asserts a fact the language does
        #: not have, where silence leaves the reading to be learned where it
        #: is true -- on the word's card, which carries it already. The
        #: section-level fallback is the shape's too: `ん` keeps its [ɴ] there
        #: while `食` has nothing above its etymologies to take.
        #: And not where the language reads the character several ways: 務's
        #: page numbers one etymology, so its `Kanji` block inherits the
        #: reading of the single word つとむ written with it and looks like
        #: the character's own. It is not. `script.speaks` is the rule, and
        #: Japanese is the language it is about.
        speaks = speaks and script.speaks(character, self.lang)
        readings = entry[1].ipa if entry and speaks else ()
        if page is not None and speaks and not readings:
            readings = page.ipa
        recordings = entry[1].audio_urls if entry and speaks else ()
        if page is not None and speaks and not recordings:
            recordings = page.audio_urls
        index = len(self.glosses)
        self.glosses.append(
            Gloss(
                index=index,
                first_sentence=self.position,
                surface=surface,
                #: Its own title, as a concept's and a rule's are.
                lemma=surface,
                #: The page the shape was read from, or none at all when the
                #: Unicode name is what the card carries.
                entry=page.title if page is not None else "",
                definition=definition,
                language=page.language if page is not None else name_of(self.lang),
                ipa=readings,
                audio_urls=recordings,
                audios=self._audios(page, recordings) if page is not None else (),
                key=gloss_key(*key),
                #: A production pair, unlike the other two glosses decker
                #: titles itself. Writing あ when asked for the syllable *a*
                #: is the direction a reader of a new script is weakest in,
                #: and the answer is a character rather than a name decker
                #: made up, so the question is about the writing system. That
                #: Anki cannot see the stroke the learner draws is true of
                #: every production card -- the learner marks it -- and is not
                #: a reason to withhold the card. Bru's call, 2026-09-18.
                production=True,
                title_prefix=SYMBOL_PREFIX,
                attribution="" if sense else SYMBOL_ATTRIBUTION,
            )
        )
        self.seen[key] = index
        self.symbol_count += 1
        count("gloss.symbol")
        log(f"script: {definition[:60]}", word=shown,
            level=DETAIL, kind="detail")
        return index

    def _symbol_entry(
        self, character: str, readings: tuple[str, ...] = ()
    ) -> tuple[tuple[Page, Entry] | None, Sense | None, bool]:
        """The entry and sense that talk about the character itself.

        The language's own section first, that being the section written about
        this language's writing, and the Translingual one after it for the
        characters no language claims. What each is allowed to answer with
        differs, and :data:`NOTATION_PARTS` says why. Failing both, a Han
        character is asked of the words its own language writes with it, and
        only then -- the character having no section here at all -- of
        :data:`HAN_SOURCES`.

        ``readings`` is the pronunciation of the term that asked for this
        card, and it is what picks between the words when there are several:
        see :meth:`_as_read`.

        The third answer is whether the block that spoke is the character's
        own, which is what decides whether the card carries a reading. True
        for the two sections above, false for everything below them: a
        Mandarin reading is not a fact about a kanji, and neither is the
        reading of one word that happens to be written with it.
        """
        own = self.page(character)
        asked = (
            (own, SHAPE_PARTS + NOTATION_PARTS),
            (self.translingual_page(character), SHAPE_PARTS),
        )
        for page, parts in asked:
            if page is None:
                continue
            for part in parts:
                for entry in page.entries:
                    if entry.part_of_speech == part and entry.senses:
                        return (page, entry), entry.senses[0], True
        if script.script_of(character) != script.HAN:
            return None, None, False
        #: A Han character is a morpheme before it is anything else, so where
        #: its page heads no Kanji and no Han character -- 下 heads a Kanji
        #: block that is readings and no gloss, 辺 heads Nouns and Suffixes --
        #: the word written with the character alone is what the character
        #: means, and `CJK UNIFIED IDEOGRAPH-8FBA` is what the alternative
        #: says. Only here: in an alphabet the letter and the word spelled
        #: with it are different things, and Russian `я` would come back as
        #: the pronoun.
        if own is not None:
            entry = self._as_read(own, readings)
            if entry is not None:
                return (own, entry), entry.senses[0], False
        #: And only now the other languages that write this character: the
        #: target language has said nothing about it, under any heading.
        for source in HAN_SOURCES:
            if section_of(source) == section_of(self.lang):
                #: A Chinese run has already asked its own section; asking it
                #: again under another of its codes is the same parse twice.
                continue
            borrowed = self.foreign_page(character, source)
            if borrowed is None:
                continue
            for part in SHAPE_PARTS:
                for entry in borrowed.entries:
                    if entry.part_of_speech == part and entry.senses:
                        return (borrowed, entry), entry.senses[0], False
        return None, None, False

    def _as_read(self, page: Page, readings: tuple[str, ...]) -> Entry | None:
        """The block of ``page`` that the term asking for this card reads with.

        A kanji page numbers one etymology per word written with the
        character, and they are unrelated words: 下 is した, しも, もと, げ and
        か, five blocks whose senses have nothing to do with each other.
        Taking the first was taking the top of the page, and the top of the
        page is alphabetical accident.

        The text decides instead, as it decides everything else here. 靴下 is
        read *kutsushita*, so the block whose own reading is inside the
        term's -- した, *the underneath* -- is the sense of 下 this deck met,
        and 地下 would have taken か, *down; below; beneath*. Where nothing
        matches, and where the page numbers only one word anyway, the first
        block stands as before.

        A rough test, and knowingly: rendaku and the sound changes of
        compounding mean a reading is not always inside the term's unchanged,
        and a character met first in 今日 is in a word no character is read in
        at all. It costs nothing when it fails -- the answer is the first
        block, which is what there was before it -- and it is right whenever
        it fires.
        """
        blocks = [entry for entry in page.entries if entry.senses]
        if not blocks:
            return None
        sounds = {_bare(reading) for reading in readings}
        if sounds:
            for entry in blocks:
                for reading in entry.ipa:
                    bare = _bare(reading)
                    if bare and any(bare in sound for sound in sounds):
                        return entry
        return blocks[0]

    def translingual_page(self, character: str) -> Page | None:
        """The character's page, cut to the section no language claims."""
        if character not in self.translingual:
            self.translingual[character] = pages.fetch(
                character, edition=self.edition, lang=TRANSLINGUAL,
                refresh=self.refresh,
            )
        return self.translingual[character]

    def foreign_page(self, character: str, lang: str) -> Page | None:
        """The character's page, cut to a section that is not this run's.

        The page itself is already cached by title, so a Han character asked
        of Chinese after Japanese costs a parse and no fetch at all.
        """
        if (character, lang) not in self.borrowed:
            self.borrowed[(character, lang)] = pages.fetch(
                character, edition=self.edition, lang=lang, refresh=self.refresh
            )
        return self.borrowed[(character, lang)]

    def concepts_of(self, sense: Sense) -> tuple[int, ...]:
        """Gloss the terminology ``sense`` explains its word with.

        A form-of definition is written in terms the learner may not have --
        "first-person singular present indicative of gritar" is four pieces of
        grammar and one word -- and Wiktionary links each of them to the
        glossary entry that explains it, which is what tells terminology from
        the words around it without a vocabulary of decker's own.
        """
        if not self.concepts:
            return ()
        if not self.glossary():
            #: The page itself is missing, which is not three hundred broken
            #: links. It is read from Wikimedia whatever source the pages came
            #: from, so the reason is that Wikimedia could not be reached and
            #: nothing was cached from an earlier run. There is nothing to
            #: resolve against, so the stage stands down rather than counting
            #: every anchor as an entry that does not exist.
            log(
                f"[decker] could not read {pages.GLOSSARY_PAGE} and none is "
                "cached; no concept cards this run",
                kind="warn",
            )
            self.concepts = False
            return ()
        found = []
        for anchor in sense.concepts:
            concept = self.glossary().get(anchor)
            if concept is None:
                self.unresolved[anchor] += 1
                continue
            found.append(self.concept(concept))
        return tuple(index for index in found if index is not None)

    def concept(self, concept: Concept) -> int | None:
        """Append a gloss for one glossary entry, or find the one standing.

        Identity is the same pair every other gloss has -- what the card is
        titled and what it teaches -- so the several anchors that reach one
        entry collapse into one card, and a previously built deck's copy of it
        is left out the way any other known gloss is.
        """
        surface = f"{CONCEPT_PREFIX}{concept.name}"
        key = (surface, concept.description)
        if key in self.seen:
            return self.seen[key]
        if gloss_key(*key) in self.known:
            self.skipped += 1
            count("gloss.known")
            return None
        index = len(self.glosses)
        self.glosses.append(
            Gloss(
                index=index,
                first_sentence=self.position,
                surface=surface,
                #: Its own title: a concept has no inflected and lemmatized
                #: form to tell apart, and printing one under the other would
                #: only say the same thing twice.
                lemma=surface,
                title_prefix=CONCEPT_PREFIX,
                title_prose=concept.name,
                entry=pages.GLOSSARY_PAGE,
                definition=concept.description,
                #: What the text is *about* is grammar, not a language, but
                #: this field is read by the translator as the language a card
                #: teaches, and that is the run's target whatever the card
                #: carries. Where the entry is linked from, the anchor below
                #: answers instead.
                language=name_of(self.lang),
                anchor=concept.anchor,
                key=gloss_key(*key),
                production=False,
            )
        )
        self.seen[key] = index
        self.concept_count += 1
        count("gloss.concept")
        return index

    def add_unknown(self, surface: str, explanation: str, model: str) -> int | None:
        """Append the card for a foreign word, explained by the model.

        No entry, because there is none -- that is what put the word here --
        so the card credits the model and links nowhere, and carries no
        production pair: a learner cannot be asked to produce a word of another
        language from a sentence about it.
        """
        key = (surface, explanation)
        if key in self.seen:
            return self.seen[key]
        if gloss_key(*key) in self.known:
            self.skipped += 1
            count("gloss.known")
            return None
        #: The word is the one thing on this card that is not the model's
        #: prose, and it is the half in a script the reader may not have: a
        #: misspelling and a foreign word are both spelled in the text's own
        #: writing system.
        depends_on = self.symbols_in(surface)
        index = len(self.glosses)
        self.glosses.append(
            Gloss(
                index=index,
                first_sentence=self.position,
                surface=surface,
                lemma=surface,
                entry="",
                definition=explanation,
                language=name_of(self.lang),
                depends_on=depends_on,
                key=gloss_key(*key),
                production=False,
                attribution=UNKNOWN_ATTRIBUTION.format(model=model or "a model"),
            )
        )
        self.seen[key] = index
        self.by_surface.setdefault(surface, index)
        self.foreign_count += 1
        count("gloss.foreign")
        return index

    def bundle_of(self, sense: Sense) -> tuple[str, ...]:
        """The feature bundle a form-of sense expresses.

        The design asks for Wiktionary's form-of prose "normalized to their
        concept", and the prose already carries the normalization: every piece
        of terminology in it is linked to the glossary entry that explains it,
        and several spellings reach one entry. The entry's own name is
        therefore the canonical form of the feature, `first_person` and
        `1st_person` alike. Sorted, because the order a definition names its
        features in is the definition's and not the bundle's.

        Without the glossary -- `--no-concepts`, which also means the page is
        never fetched -- the anchors are used as they come. They are already
        Wiktionary's own spelling of the feature, so the bundles are coarser
        than they could be and never wrong.
        """
        if not sense.concepts:
            return ()
        glossary = self.glossary() if self.concepts else {}
        names = []
        for anchor in sense.concepts:
            concept = glossary.get(anchor)
            names.append(concept.name if concept else anchor.replace("_", " "))
        return tuple(sorted(set(names)))

    def rule(self, rule: Rule, depends_on: tuple[int, ...]) -> int | None:
        """Append the explanation card of one morphological rule.

        Appended when its second example is already in the list, never before,
        so the dependency points backwards: deck construction resolves a
        dependency to the card that introduced it, and a card that does not
        exist yet cannot be pointed at.
        """
        surface = rule.title()
        key = (surface, rule.description)
        if key in self.seen:
            return self.seen[key]
        if gloss_key(*key) in self.known:
            self.skipped += 1
            count("gloss.known")
            return None
        #: The title carries the representative word, which is a word of the
        #: language and written in its script.
        depends_on = _merge(depends_on, self.symbols_in(surface))
        index = len(self.glosses)
        self.glosses.append(
            Gloss(
                index=index,
                first_sentence=self.position,
                surface=surface,
                #: Its own title, as a concept's is: a rule has no inflected
                #: form and no lemma of its own.
                lemma=surface,
                title_prefix=RULE_PREFIX,
                #: The bundle alone: the representative beside it in the title
                #: is a word of the language and stays in it.
                title_prose=rule.label,
                #: The page its representative was glossed from, which is what
                #: a reader following the card would want to see -- the rule
                #: itself is not on any page.
                entry=rule.entry,
                definition=rule.description,
                language=name_of(self.lang),
                depends_on=depends_on,
                key=gloss_key(*key),
                production=False,
                attribution=RULE_ATTRIBUTION.format(model=rule.model or "a model"),
            )
        )
        self.seen[key] = index
        self.rule_count += 1
        count("gloss.rule")
        return index

    def _audios(self, page: Page, urls: tuple[str, ...]) -> tuple[str, ...]:
        """The given recordings, downloaded, minus the ones that failed.

        Given rather than read off the page: which of a page's recordings
        belong to a gloss is the etymology block's question, and the block is
        what asked for these.
        """
        if not self.audio or not urls:
            return ()
        if not pages.carries_media(page.source):
            self.silent.add(page.title)
            return ()
        self.offered += len(urls)
        paths = (pages.audio_path(url) for url in urls)
        return tuple(str(path) for path in paths if path)


def _bare(reading: str) -> str:
    """A transcription stripped to the sounds, for comparing one with another.

    Wiktionary brackets a phonetic reading and slashes a phonemic one, and a
    block may carry several separated by commas. Only enough is taken off to
    let one reading be looked for inside another: the delimiters, the
    whitespace and the stress and length marks, which compounding moves
    around. The symbols themselves are left exactly as they are, since it is
    the sounds that have to match.
    """
    return reading.strip("[]/ ").replace("ˈ", "").replace("ˌ", "").replace(" ", "")


def _merge(*groups: tuple[int, ...]) -> tuple[int, ...]:
    """Several dependency lists as one, in order, without repeats."""
    found: list[int] = []
    for group in groups:
        for index in group:
            if index not in found:
                found.append(index)
    return tuple(found)


def build(
    sentences: list["SentenceTerms"],
    *,
    target_lang: str,
    edition: str,
    model: str | None = None,
    host: str | None = None,
    disambiguate: bool = True,
    audio: bool = True,
    concepts: bool = True,
    components: bool = True,
    rules: bool = True,
    unknowns: str = "fix",
    refresh: bool = False,
    refresh_answers: bool = False,
    known: frozenset[str] = frozenset(),
    teach_script: bool = False,
    mother_lang: str = "en",
) -> list[Gloss]:
    """Turn term extraction's output into the design's list of glosses.

    ``limit`` stops the walk once that many glosses stand, and the run carries
    on to the cards with what it has -- the same end Ctrl+C reaches, reached
    on a count instead of on a key. It is checked between terms, so the last
    term's senses, symbols and components are all made and the list overshoots
    a little rather than cutting a word in half.
    """
    reads = script.scripts_of(mother_lang) if teach_script else ()
    if teach_script and reads is None:
        #: The stage stands down rather than guessing: decker would be saying
        #: which writing systems this reader already has, and both ways of
        #: being wrong -- teaching them their own alphabet, or leaving a
        #: script untaught -- look like working cards.
        log(
            f"[decker] --teach-script does not know which scripts a reader of "
            f"{name_of(mother_lang)} already reads, so nothing is taught about "
            "the script (decker.script._READS is where one goes)",
            kind="warn",
        )
        teach_script = False
        reads = ()
    disambiguator = Disambiguator(
        model=model or default_model(),
        host=host,
        enabled=disambiguate,
        refresh=refresh_answers,
    )
    morphology = Morphology(
        lang=target_lang,
        model=model or default_model(),
        host=host,
        enabled=rules,
        refresh=refresh_answers,
        categories=_categories(sentences),
    )
    builder = _Builder(
        edition=edition,
        lang=target_lang,
        disambiguator=disambiguator,
        morphology=morphology,
        unknowns=Unknowns(
            lang=target_lang,
            model=model or default_model(),
            host=host,
            refresh=refresh_answers,
            mode=unknowns,
        ),
        audio=audio,
        concepts=concepts,
        components=components,
        refresh=refresh,
        known=known,
        teach_script=teach_script,
        reads=reads,
    )
    with console.phase(
        "glossing",
        sum(len(one.text) for one in sentences),
        unit="characters",
        items=len(sentences),
    ):
        for position, sentence in enumerate(sentences):
            if console.skipping():
                #: What is glossed is glossed; the deck is built from it and
                #: the run carries on to the cards.
                break
            builder.position = position
            around = _around(sentences, position)
            log(f"[decker] {sentence.text[:70]}", level=DETAIL, kind="detail")
            for term in sentence.terms:
                _gloss_term(builder, term, sentence.text, around)
            console.advance(len(sentence.text))
    if audio and builder.glosses and not builder.offered:
        #: A source that carries no media at all is not the same as a word
        #: that happens to have no recording, and the two look identical on
        #: a card. A local mirror is the ordinary reason: media is in no dump.
        log(
            "[decker] no recordings offered by this source; cards will have no "
            "audio (a local Wiktionary carries none: media is in no dump)",
            kind="warn",
        )
    elif audio and builder.silent:
        #: The mixed case, which the cache now makes ordinary: some pages were
        #: read from a mirror's cache entry and some from Wikimedia's, so the
        #: deck has audio on most cards and none on these, for a reason that
        #: has nothing to do with the words.
        count = len(builder.silent)
        log(
            f"[decker] {count} page{'' if count == 1 else 's'} came from a "
            "source with no media; those cards have no audio (--refresh-pages "
            "against Wikimedia gets it, at the cost of naming them to it)",
            kind="warn",
        )
    if builder.skipped:
        log(f"[decker] {builder.skipped} glosses already taught, left out")
    if builder.unresolved:
        #: An anchor the glossary has no entry for is terminology decker can
        #: see and cannot explain, so it is counted rather than guessed at.
        total = sum(builder.unresolved.values())
        names = ", ".join(anchor for anchor, _ in builder.unresolved.most_common(5))
        log(
            f"[decker] {total} links to glossary entries that do not exist "
            f"({len(builder.unresolved)} distinct: {names}); no cards for those",
            level=VERBOSE, kind="warn",
        )
    if builder.concept_count:
        log(
            f"[decker] {builder.concept_count} of them are concepts "
            f"({pages.GLOSSARY_PAGE})"
        )
    if builder.composed:
        log(
            f"[decker] {len(builder.composed)} of them are the terms an "
            "etymology decomposes a word into (des- + cargar), taught before "
            "the word that is made of them"
        )
    if builder.symbol_count:
        log(
            f"[decker] {builder.symbol_count} of them are symbols: every "
            "character of a term is taught before the term is"
        )
    elif teach_script:
        #: Nothing foreign was found, which for a Latin-script language read
        #: by a reader of English is the right answer and not a failure -- and
        #: an unexpected one often enough to be worth a line.
        log("[decker] every term is written in the mother tongue's own script; "
            "--teach-script added nothing")
    morphology.report()
    if builder.unknowns is not None:
        for line in builder.unknowns.report():
            log(line)
    if builder.foreign_count:
        log(
            f"[decker] {builder.foreign_count} of them are foreign words, "
            "explained by the model rather than by Wiktionary"
        )
    log(f"[decker] {len(builder.glosses)} glosses", kind="head")
    return builder.glosses


#: How much text the disambiguation prompt is given around an occurrence, in
#: words, counting the occurrence's own sentence. A sentence is the design's
#: unit and it is the right one for prose; dialogue is where it runs out --
#: Bru's Russian series folds into 6,158 sentences with a *median of six
#: tokens*, and six tokens is not enough to tell one sense of a word from
#: another. Below this floor the neighbouring sentences are added, alternately
#: behind and ahead, until it is reached or the text runs out.
#:
#: Measured rather than guessed, and the measurement is in
#: `definition-fetching.md`: twenty is the least that recovers the benchmark
#: check a five-word sentence loses, and more than twenty buys nothing.
CONTEXT_WORDS = 20

#: And only for these. Context is given to a word that *has* a meaning to
#: choose; a preposition or a determiner has a page of fine distinctions
#: instead, and on those the extra sentences can make a model hedge rather than
#: choose. UD's open classes, plus the interjection, which is where `vaya`
#: lives when it is not a verb.
#:
#: **This is one model's guard, and the measurement says so.** It was chosen on
#: `gemma4:latest`, whose Hebrew clitic cards go from 8 to 27 without it -- the
#: prefixes carry twenty-three senses apiece and it keeps most of them once it
#: has a passage to reason over. Asked of every model on the box, Hebrew, cards
#: from the prefix entries, rule on against rule off:
#:
#:     gemma4:latest      8 -> 27      the reason this exists
#:     qwen3.5:4b        12 -> 15      the default, barely moved
#:     gemma3:4b         19 -> 19      unmoved; it keeps everything either way
#:     qwen3:14b          9 ->  8      one card *better* without it
#:
#: And on the 24-check benchmark it changes nothing for anyone: 22, 21, 16 and
#: 23 of 24 with the rule and without it, gloss counts within two. So it is
#: kept as cheap insurance for a model a `--model` flag away, not because the
#: default needs it -- and if it is ever in the way, this is the note that says
#: dropping it costs three cards in Hebrew and nothing anywhere measured.
CONTEXT_FOR = frozenset({"NOUN", "PROPN", "VERB", "ADJ", "ADV", "INTJ"})


def _around(sentences: list["SentenceTerms"], position: int) -> tuple[str, str]:
    """The neighbouring sentences this one needs to reach :data:`CONTEXT_WORDS`.

    Symmetrically, and behind first: in dialogue what was just said is what a
    line answers. A sentence already at the floor gets nothing, which is every
    sentence of ordinary prose, so a book's prompts are exactly what they were.
    Computed once per sentence rather than once per term -- every term of a
    sentence shares its neighbours.
    """
    words = len(sentences[position].text.split())
    before: list[str] = []
    after: list[str] = []
    back, ahead = position - 1, position + 1
    while words < CONTEXT_WORDS and (back >= 0 or ahead < len(sentences)):
        take_back = back >= 0 and (len(before) <= len(after) or ahead >= len(sentences))
        if take_back:
            text = sentences[back].text
            before.insert(0, text)
            back -= 1
        else:
            text = sentences[ahead].text
            after.append(text)
            ahead += 1
        words += len(text.split())
    return " ".join(before), " ".join(after)


def _categories(sentences: list["SentenceTerms"]) -> tuple[str, ...]:
    """Every morphological category the parse marks anywhere in the text.

    Read off the terms rather than off the document, because the terms are
    what this stage was given -- and they are nearly all of it: a category a
    language inflects for is marked on words that have Wiktionary entries.
    """
    return tuple(
        sorted(
            {
                category
                for sentence in sentences
                for term in sentence.terms
                for category in term.features
            }
        )
    )


def _gloss_term(
    builder: _Builder, term: Term, sentence: str, around: tuple[str, str] = ("", "")
) -> None:
    candidates = builder.own_pages(term) or [
        page for page in (builder.first_page(term.entries),) if page is not None
    ]
    if not candidates:
        _no_entry(builder, term, sentence, around)
        return
    #: What the word cost the deck, said once per occurrence. A term with an
    #: entry that ends up adding nothing -- every sense already taught, every
    #: instance culled by the rules stage -- otherwise looks exactly like one
    #: that was never reached, and the two want telling apart while reading a
    #: run go past.
    before = len(builder.glosses)

    #: The occurrence is bracketed inside its own sentence and the neighbours
    #: go around the outside, so the model is shown a passage with exactly one
    #: mark in it however much context the passage carries -- and no neighbours
    #: at all for a closed-class word, which is the other half of the choice
    #: recorded at :data:`CONTEXT_FOR`.
    marked = mark_occurrence(sentence, term.spans)
    if term.upos in CONTEXT_FOR:
        marked = " ".join(part for part in (around[0], marked, around[1]) if part)
    page, senses = _pooled_senses(builder, candidates, term, marked)
    surface = _spelling(page)
    for sense in senses:
        #: Before anything decides whether this occurrence keeps a card of its
        #: own: what a form-of definition points at is glossed either way. The
        #: design's culling drops the instance and keeps the base word, which
        #: is only a sentence away from being the opposite by accident.
        depends_on = _dependencies(
            builder, page, sense, surface, term.lemma, marked,
            frozenset({page.title}),
        )
        if (surface, sense.definition) in builder.seen:
            #: The same form in the same sense, met again. It is one card
            #: however many times the text says it, so it is not another
            #: instance of its rule either.
            builder.add(
                page, surface=surface, lemma=term.lemma, sense=sense,
                depends_on=depends_on,
            )
            continue
        outcome = _morphology(builder, page, surface, sense)
        if not outcome.keep:
            continue
        index = builder.add(
            page,
            surface=surface,
            lemma=term.lemma,
            sense=sense,
            depends_on=depends_on,
        )
        if outcome.rule is None or index is None:
            continue
        if (examples := builder.morphology.example(outcome.rule, index)) is not None:
            builder.rule(outcome.rule, examples)

    added = len(builder.glosses) - before
    if added:
        log(f"{added} gloss{'' if added == 1 else 'es'}",
            word=term.surface, level=VERBOSE, kind="found")
    else:
        log("nothing new to teach", word=term.surface,
            level=VERBOSE, kind="dropped")


def _no_entry(
    builder: _Builder, term: Term, sentence: str, around: tuple[str, str]
) -> None:
    """A word Wiktionary has no entry for, and what becomes of it.

    Dropped, before this stage existed and still whenever the model cannot be
    reached or says it is nothing. Otherwise: a misspelling is looked up as the
    word that was meant and glossed as that word, a foreign word the reader
    would not know is taught with the model's own explanation, and a foreign
    word they would know is dropped like any other thing not worth a card.
    """
    unknowns = builder.unknowns
    if unknowns is None or not unknowns.enabled:
        log(
            f"no {builder.lang} entry ({', '.join(term.entries)})",
            word=term.surface, level=VERBOSE, kind="missing",
        )
        return

    marked = mark_occurrence(sentence, term.spans)
    passage = " ".join(part for part in (around[0], marked, around[1]) if part)
    verdict = unknowns.verdict(term.surface, passage, name_of(builder.lang))
    if verdict is None:
        log(
            f"no {builder.lang} entry; the model would not say what it is",
            word=term.surface, level=VERBOSE, kind="missing",
        )
        return

    if verdict.is_correction:
        page = builder.page(verdict.correction)
        if page is None or not page.senses:
            log(
                f"looks like {verdict.correction!r}, which has no entry either",
                word=term.surface, level=VERBOSE, kind="missing",
            )
            return
        log(
            f"-> {verdict.correction!r} (spelling)",
            word=term.surface, level=VERBOSE, kind="fixed",
        )
        #: Glossed as the word that was meant, and fronted with it: the text's
        #: spelling is a mistake in the text, and a card teaching it would
        #: teach the mistake.
        corrected = dataclasses.replace(
            term, surface=verdict.correction, joined="", entries=(verdict.correction,)
        )
        _gloss_term(builder, corrected, sentence, around)
        return

    if verdict.is_native:
        index = builder.add_unknown(term.surface, verdict.explanation, unknowns.model)
        if index is not None:
            log(
                f"a {name_of(builder.lang)} word Wiktionary lacks; explained "
                "by the model",
                word=term.surface, level=VERBOSE, kind="fixed",
            )
        return

    if verdict.kind == "foreign":
        if verdict.widely_known and not unknowns.teaches_known_foreign():
            log(
                "foreign and widely known; no card",
                word=term.surface, level=VERBOSE, kind="dropped",
            )
            return
        if not verdict.explanation:
            return
        index = builder.add_unknown(term.surface, verdict.explanation, unknowns.model)
        if index is not None:
            log(
                "taught as a foreign word",
                word=term.surface, level=VERBOSE, kind="fixed",
            )
        return

    log(
        "nothing recognizable; dropped",
        word=term.surface, level=VERBOSE, kind="dropped",
    )


def _morphology(
    builder: _Builder, page: Page, surface: str, sense: Sense
) -> Outcome:
    """What the rules stage makes of one occurrence of an inflected form.

    Only occurrences in the text are put to it. A word reached through a
    definition -- the `conocer` that `conocí` is explained in terms of -- is a
    dependency rather than an instance, and culling one would take away the
    card the instance was told to keep.
    """
    targets = builder.references_of(page).get(sense.definition, ())
    if not targets:
        return Outcome()
    base = targets[0]
    return builder.morphology.consider(
        surface=surface,
        base=base,
        bundle=builder.bundle_of(sense),
        label=label_of(sense.definition, base),
        prose=sense.definition,
        entry=page.title,
    )


def _referenced(
    builder: _Builder,
    page: Page,
    sense: Sense,
    marked: str,
    chain: frozenset[str],
) -> tuple[int, ...]:
    """Gloss the words ``sense`` describes its own word in terms of.

    A definition that only points somewhere -- `diminutive of pata` -- teaches
    nothing unless the word it points at is learned too, and that word is named
    in the definition rather than in the parse, so it is often not the term's
    lemma and often not in the text at all. One sense of it is wanted, the one
    the pointer relies on, so each reference is a single gloss. The chain of
    titles already being resolved keeps a pair that defines each other in terms
    of the other from looping.
    """
    return tuple(
        index
        for title in builder.references_of(page).get(sense.definition, ())
        if title not in chain
        and (index := _dependency(builder, title, marked, chain)) is not None
    )


def _composed(
    builder: _Builder,
    page: Page,
    sense: Sense,
    marked: str,
    chain: frozenset[str],
) -> tuple[int, ...]:
    """Gloss the terms this sense's etymology decomposes its word into.

    The other half of what a word depends on, and it is a different half: a
    form-of points at the word this one is an inflection *of*, an etymology
    names the words this one is *made of*. `descargar` is `des-` and `cargar`,
    and a reader who has neither has been handed a card that says its own
    answer in words they have not met. Recursively, because a component is a
    word like any other and may be a sum itself -- `cargar` is `carga` and
    `-ar` -- and the chain of titles being resolved is what stops a pair that
    name each other from looping.

    Only the components of *this* sense's etymology block, and only those in
    the language being taught: the Latin, the Arabic and the Quechua an
    etymology walks back through get no cards, which is Bru's call of
    2026-09-14 and still holds. What changed on 2026-09-20 is the sum: a
    component of the same language is a word of the text's own language, and
    the reader meets it in the word in front of them.
    """
    if not builder.components:
        return ()
    dependencies = []
    for title in page.etymons_of(sense):
        if title in chain:
            continue
        fresh = title not in builder.by_surface
        index = _dependency(builder, title, marked, chain)
        if index is None:
            continue
        if fresh:
            builder.composed.add(title)
            log(f"a component of {page.title!r}", word=title,
                level=VERBOSE, kind="found")
        dependencies.append(index)
    return tuple(dependencies)


def _dependency(
    builder: _Builder,
    title: str,
    marked: str,
    chain: frozenset[str],
) -> int | None:
    """Gloss one word another gloss leans on, in the one sense it leans on.

    Shared by both kinds of dependency -- the word a definition points at and
    the terms an etymology sums -- because what has to happen to either is the
    same: the page, one sense of it chosen against the passage the dependent
    word was met in, and whatever *that* sense depends on in turn.

    ``None`` where there is no page, no sense the model will stand behind, or
    a previously built deck already teaches it: such a dependency is simply
    not depended upon, the learner having met it.
    """
    target = builder.page(title)
    if target is None:
        return None
    labelled = target.senses
    kept = builder.disambiguator.keep(
        tuple(one for _, one in labelled),
        sentence=marked,
        surface=title,
        title=f'"{title}"',
        language=target.language,
        parts_of_speech=tuple(part for part, _ in labelled),
        single=True,
    )
    if not kept:
        return None
    return builder.add(
        target,
        surface=title,
        lemma=title,
        sense=kept[0],
        depends_on=_dependencies(
            builder, target, kept[0], title, title, marked, chain | {title}
        ),
    )


def _dependencies(
    builder: _Builder,
    page: Page,
    sense: Sense,
    surface: str,
    lemma: str,
    marked: str,
    chain: frozenset[str],
) -> tuple[int, ...]:
    """Everything one gloss has to be met after, in the order it wants them.

    Three questions asked of the same sense: the plain reading a figure of
    speech stands on, the word a form-of points at, and the terms an etymology
    sums it out of.
    """
    return (
        _plainly(builder, page, sense, surface, lemma, marked, chain)
        + _referenced(builder, page, sense, marked, chain)
        + _composed(builder, page, sense, marked, chain)
    )


#: Labels that make a sense a *figure* of the word rather than the word: the
#: reading is real, and it is built on a plain sense the learner has to have
#: first. `мрак` in a Stigmata lyric was glossed `(poetic) despair` -- which is
#: defensible in the line and is the whole of what the deck then taught about
#: the word, a metaphor with nothing under it. Bru's call, 2026-09-17: when one
#: of these is chosen, ask again with the labelled senses taken out, and hang
#: the marked card off the plain one the way a form-of card hangs off its base
#: word.
#:
#: Not every parenthetical: `(anatomy)`, `(with dative)`, `(impersonal)` say
#: which *use* of the word this is and depend on nothing. These are the ones
#: that say the sense is a figure, a register or an age -- a reading a learner
#: cannot arrive at from the word alone.
_MARKED = frozenset({
    "archaic", "colloquial", "colloquially", "dated", "euphemistic",
    "figurative", "figuratively", "humorous", "ironic", "literary", "obsolete",
    "poetic", "poetically", "slang",
})

#: A definition's leading qualifier, which is where Wiktionary writes them:
#: `(figuratively, poetic) to die`.
_QUALIFIER = re.compile(r"^\(([^)]*)\)")


def is_marked(definition: str) -> bool:
    """Whether ``definition`` is labelled as a figure of its word."""
    return any(
        part.strip().casefold() in _MARKED
        for part in leading_qualifier(definition).strip("()").split(",")
    )


def leading_qualifier(definition: str) -> str:
    """The label a definition opens with, parentheses included, or nothing."""
    found = _QUALIFIER.match(definition.strip())
    return found.group(0) if found else ""


def _plainly(
    builder: _Builder,
    page: Page,
    sense: Sense,
    surface: str,
    lemma: str,
    marked: str,
    chain: frozenset[str],
) -> tuple[int, ...]:
    """The plain sense a marked one stands on, glossed first, or nothing.

    One more call, and only for the senses that carry a label: the same page,
    its labelled senses removed, asked for the one the passage would otherwise
    have taken. The card it makes is an ordinary gloss of the same spelling, so
    a deck that already teaches it depends on what it has rather than saying it
    twice, and the marked sense's card is ordered after it.

    A page whose every sense is labelled gets nothing -- there is no plain
    reading to teach -- and neither does a page with one sense, which never
    reaches the model at all.
    """
    if not is_marked(sense.definition):
        return ()
    plain = [(part, one) for part, one in page.senses if not is_marked(one.definition)]
    if not plain:
        return ()
    kept = builder.disambiguator.keep(
        tuple(one for _, one in plain),
        sentence=marked,
        surface=surface,
        title=f'"{page.title}"',
        language=page.language,
        parts_of_speech=tuple(part for part, _ in plain),
        sources=tuple(page.title for _ in plain),
        single=True,
    )
    if not kept:
        return ()
    log(
        f"{sense.definition[:40]!r} is a figure; teaching "
        f"{kept[0].definition[:40]!r} first",
        word=surface, level=VERBOSE, kind="found",
    )
    index = builder.add(
        page,
        surface=surface,
        lemma=lemma,
        sense=kept[0],
        depends_on=_referenced(builder, page, kept[0], marked, chain)
        + _composed(builder, page, kept[0], marked, chain),
    )
    return () if index is None else (index,)


#: Words that mark a definition as describing its word in terms of another,
#: rather than giving a meaning of its own.
_GRAMMAR = re.compile(
    r"\b(inflection|form|spelling|participle|gerund|degree|diminutive|augmentative"
    r"|superlative|clipping|abbreviation|accusative|dative|nominative|genitive"
    r"|vocative|singular|plural|indicative|subjunctive|imperative|imperfect"
    r"|preterite|conditional|(?:first|second|third)-person)\b",
    re.IGNORECASE,
)
#: The referenced word itself, after the "of" such a definition hangs it on.
_TARGET = re.compile(r"\bof\s+([^\s,;:.()\[\]“”\"]+)")


def _targets(definition: str, own: str) -> tuple[str, ...]:
    """The words ``definition`` describes its own word in terms of."""
    if not _GRAMMAR.search(definition):
        return ()
    found = []
    for match in _TARGET.finditer(definition):
        target = match.group(1).strip("“”\"'")
        if target and target != own and target not in found:
            found.append(target)
    return tuple(found)


def references(page: Page) -> dict[str, tuple[str, ...]]:
    """Per definition of ``page``, the words it describes that word in terms of.

    Wiktionary names the referenced word once per part-of-speech block and lets
    the lines under it continue -- `inflection of ir: ...present subjunctive`
    followed by a bare `third-person singular imperative`. A bare line is only
    given the block's word when it is itself grammatical description, so a real
    definition sitting in the same block does not inherit a dependency.
    """
    found: dict[str, tuple[str, ...]] = {}
    for entry in page.entries:
        for sense in entry.senses:
            #: Wiktionary's own markup first, the prose only where there is
            #: none. Measured over nine Spanish sources: the two agree on
            #: 1,228 definitions and disagree on nine, and the markup is right
            #: in all nine -- the prose reader truncates a multi-word lemma to
            #: its first word. The markup also catches sixteen relations the
            #: word list does not know (`female equivalent of`, `ellipsis
            #: of`), and misses fifty-five that are written by hand rather
            #: than through a template, which is what the fallback is for.
            targets = tuple(
                title for title in sense.targets if title != page.title
            ) or _targets(sense.definition, page.title)
            if targets:
                found[sense.definition] = targets
        #: Only a block that *opens* by naming the word is a form-of block.
        #: Keying off any sense let `ir`, whose tenth definition mentions the
        #: past participle of reflexive verbs, hand `reflexive` to its
        #: neighbours as though it were their lemma.
        first = entry.senses[0].definition if entry.senses else ""
        block = found.get(first, ())
        if not block:
            continue
        for sense in entry.senses:
            if sense.definition not in found and _GRAMMAR.search(sense.definition):
                found[sense.definition] = block
    return found


def mark_occurrence(sentence: str, spans: tuple[tuple[int, int], ...]) -> str:
    """Bracket this occurrence inside the sentence it was found in.

    Two occurrences of one form in a sentence are two different words as often
    as not -- `Vaya, vaya a dormir` is an interjection and a subjunctive -- and
    an unmarked prompt describes them identically, so the model cannot answer
    differently even in principle.
    """
    if not spans:
        return sentence
    out, cursor = [], 0
    for start, end in spans:
        if not 0 <= cursor <= start < end <= len(sentence):
            return sentence
        out += [sentence[cursor:start], "⟨", sentence[start:end], "⟩"]
        cursor = end
    out.append(sentence[cursor:])
    return "".join(out)


def _capital_is_the_lines(term: Term, candidates: list[Page]) -> bool:
    """Whether the parse read a capital that belongs to the position.

    `PROPN` on a word whose capital is the position's is the one tag the
    capital itself fabricates. Stanza reads `Надежда казалась мне солью` as a
    proper noun and `надежда казалась мне солью` as a noun -- one letter, and
    with it the lemma -- and the prompt then tells the model to *prefer a sense
    listed under that part of speech*, which is the given name. Term extraction
    has already said the capital is suspect by offering the lower-case spelling
    as well; handing the tag it produced to the model as evidence takes that
    back, and outvoted the `надежда` entry sitting in the same list. Bru found
    the card in the Stigmata deck, 2026-09-16.

    Only where the lower-case spelling reached a page, so the hint is kept
    everywhere it costs nothing -- a sentence really beginning with a name has
    nothing else in the listing to be steered away from -- and the hint stays
    whole for every other tag, which is what it was written for: `ADP` against
    the name of a Hebrew letter is not a guess the capital made.
    """
    if term.upos != "PROPN" or not term.positional_capital:
        return False
    if not any(page.title[:1].islower() for page in candidates):
        return False
    log(
        "the parse reads it as a proper noun, which its line-initial capital "
        "may be the whole of; telling the model so instead",
        word=term.surface, level=VERBOSE, kind="detail",
    )
    return True


def _pooled_senses(
    builder: _Builder, candidates: list[Page], term: Term, sentence: str
) -> tuple[Page, tuple[Sense, ...]]:
    """Disambiguate across every candidate page at once.

    The senses of `Bueno` and `bueno` are numbered as one list, so the model
    chooses a meaning rather than the pipeline choosing a spelling. The page
    that most of the surviving senses came from is the one the gloss is built
    from, since a gloss carries one entry, one etymology and one reading.
    """
    labelled = [
        (page, part, sense)
        for page in candidates
        for part, sense in page.senses
    ]
    if not labelled:
        return candidates[0], ()
    #: One predicate, two uses: the tag the capital made is not passed on,
    #: and the reason it is not is what goes in its place.
    positional_capital = _capital_is_the_lines(term, candidates)
    kept = builder.disambiguator.keep(
        tuple(sense for _, _, sense in labelled),
        sentence=sentence,
        surface=term.surface,
        title=", ".join(f'"{page.title}"' for page in candidates),
        language=candidates[0].language,
        parts_of_speech=tuple(part for _, part, _ in labelled),
        sources=tuple(page.title for page, _, _ in labelled),
        upos="" if positional_capital else term.upos,
        positional_capital=positional_capital,
    )
    surviving = {id(sense) for sense in kept}
    chosen = [(page, sense) for page, _, sense in labelled if id(sense) in surviving]
    if not chosen:
        return candidates[0], ()

    counts = Counter(page.title for page, _ in chosen)
    winner = max(candidates, key=lambda page: (counts[page.title], -candidates.index(page)))
    dropped = [title for title in counts if title != winner.title]
    if dropped:
        log(
            f"[decker] {term.surface!r}: kept senses from {winner.title!r}, "
            f"dropping those from {', '.join(repr(t) for t in dropped)}",
            level=VERBOSE, kind="detail",
        )
    return winner, tuple(sense for page, sense in chosen if page.title == winner.title)


def _spelling(page: Page) -> str:
    """The form the card is fronted with: the entry the senses were read from.

    The card's back is one entry's -- its senses, its etymology, its reading --
    so its front is that entry's title. The capital was the first case
    this settled -- `Cuando` glossed from `cuando` is one thing to learn rather
    than two -- and the bound morpheme the second: a clitic that won its entry
    at `ל־` is fronted `ל־`, with the maqaf, because that is what the
    dictionary calls the thing the card teaches and the maqaf is the part that
    says it attaches to the next word. Bru's call, 2026-09-15.

    The third case is why this is now the whole rule. A form Wiktionary has no
    page for is glossed from its lemma's, and the text's own form used to stay
    on the front: `Упавшего` fronting `упасть`'s definition, `упасть`'s
    reading `[ʊˈpasʲtʲ]` and `упасть`'s example -- a card that asks for a
    participle and answers with an infinitive, keeping a sentence-initial
    capital on top. Bru found it in a deck he was studying, 2026-09-16. The
    text's form is what the reader met, but it is not what this card teaches,
    and nothing on the back of it says so.
    """
    return page.title

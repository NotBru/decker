"""Definition fetching: from terms to glosses.

One gloss per term, plus one for the lemma whenever the term is inflected and
Wiktionary spells the lemma under a page of its own. The inflected gloss
depends on the lemma's, and its definition is the form-of line Wiktionary
already writes -- "third-person singular preterite indicative of correr" --
which is exactly the relationship the design asks the inflected gloss to
explain. Glosses appear in the order their terms occur in the source, a
dependency always before what depends on it.

Two kinds of gloss are not a word of the text: a concept, read from
`Appendix:Glossary` for the terminology a definition is written in, and a
morphological rule, worked out in :mod:`decker.morphology` from the form-of
line itself. Both explain the machinery a definition uses rather than a word
the reader met, and neither carries a production pair.
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
from decker.console import DETAIL, VERBOSE, console, log
from decker.disambiguation import Disambiguator
from decker.languages import name_of
from decker.morphology import Morphology, Outcome, Rule, label_of
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

#: What a symbol card says when Wiktionary has no entry for the character --
#: `¿` is a redirect, and decker does not follow those -- and the Unicode
#: name is all there is. A different claim from a quotation, so it reads as
#: one, exactly as a rule's does.
SYMBOL_ATTRIBUTION = (
    "Named from the Unicode character database; the English Wiktionary has no "
    "entry for this character."
)

#: The parts of speech under which a page talks about the character as a piece
#: of writing, most telling first. `ж` heads a Russian Letter, a Particle and
#: a Noun, and only the first is what a symbol card is for; `水` heads a
#: Chinese word and a Translingual Han character, and the word already has a
#: card of its own whenever the text used it.
SHAPE_PARTS = (
    "Letter",
    "Letters",
    "Punctuation mark",
    "Diacritical mark",
    "Han character",
    "Hanzi",
    "Kanji",
    "Hanja",
    "Syllable",
    "Character",
    "Number",
    "Numeral",
)

#: And the part of speech under which it is a piece of *notation*. Kept apart
#: because a glyph is often both and the two answers are not interchangeable:
#: the Translingual `¡` is an extIPA percussive, which is the right card for
#: a reading that contains one and a false one for a Spanish sentence that
#: opens with it -- Wiktionary writes the punctuation mark on the combined
#: page `¿ ?`, which `¡` and `¿` redirect to and decker does not follow. So
#: a character met in a reading is asked about as notation, a character met in
#: the text is asked about as writing, and a text character with nothing but a
#: notation entry falls through to its Unicode name instead.
NOTATION_PARTS = ("Symbol",)

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
    #: For a concept read from `Appendix:Glossary`, where on that page it
    #: lives. Empty for an ordinary gloss, whose entry is a word and whose
    #: link goes to its language section instead.
    anchor: str = ""
    #: Whether deck construction makes the production card as well. The design
    #: gives the pair to word definitions only: asking for `Concept: dative
    #: case` or for a rule's title, given its explanation, is a question about
    #: decker's own titling and not about the language.
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
    #: Whether every character a card displays has to have been taught by one.
    teach_script: bool = False
    #: The characters the reader already reads, from their mother tongue.
    familiar: frozenset[str] = frozenset()
    #: Whether the prose a card carries is scanned along with the language on
    #: it. It is the text the card shows only when the cards are left in the
    #: edition's language -- otherwise what the reader sees is the
    #: translation, and the English under it is a stage in the pipeline and
    #: not a symbol anybody is shown.
    prose: bool = True
    #: Characters already dealt with, to the gloss that teaches them: an index,
    #: or ``None`` where there is nothing to depend on -- a previous deck
    #: taught it, or the character could not be resolved at all.
    symbols: dict[str, int | None] = field(default_factory=dict)
    #: Characters being resolved right now. A letter's own definition is
    #: written in its own alphabet, so `ж` reaches `е` reaches `ж`, and a
    #: dependency on a gloss that does not exist yet is a cycle the shuffle
    #: would have to break. The second visit simply does not depend on the
    #: first; both are taught either way.
    pending: set[str] = field(default_factory=set)
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
            log(f"[decker]   fetching {title}", level=DETAIL, kind="detail")
            self.fetched[title] = pages.fetch(
                title, edition=self.edition, lang=self.lang, refresh=self.refresh
            )
            #: The outcome rather than the request: a page that came back
            #: without a section in this language is the ordinary reason a word
            #: of the text gets no card, and at `-v` it is the line worth
            #: seeing. The fetch itself is one level further down.
            page = self.fetched[title]
            if page is None:
                log(f"[decker]   {title}: no {name_of(self.lang)} section",
                    level=VERBOSE, kind="missing")
            else:
                log(
                    f"[decker]   {title}: {len(page.senses)} sense"
                    f"{'' if len(page.senses) == 1 else 's'}"
                    f"{' from ' + page.source if page.source else ''}",
                    level=VERBOSE, kind="found",
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
            return None
        #: Before the gloss itself, so a concept it names is already standing
        #: and carries the lower index: the terminology inside a definition is
        #: something to be met before the definition that uses it, which is
        #: exactly what a dependency says. The script goes in front of both:
        #: a card the reader cannot read is not improved by their knowing what
        #: dative means.
        depends_on = _merge(
            depends_on,
            self.symbols_of(
                surface,
                page.headword_of(sense),
                *(example.sentence for example in sense.examples),
                *self.shown(
                    sense.definition,
                    page.etymology_of(sense) or "",
                    *(example.rendering or "" for example in sense.examples),
                ),
            ),
            self.symbols_of(*page.ipa_of(sense), notation=True),
            self.concepts_of(sense),
        )
        index = len(self.glosses)
        self.glosses.append(
            Gloss(
                index=index,
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
        return index

    def shown(self, *texts: str) -> tuple[str, ...]:
        """The prose of these, if prose is what the card will show.

        Everything a card carries that the translator may touch goes through
        here, and nothing else does.
        """
        return texts if self.prose else ()

    def symbols_of(self, *texts: str, notation: bool = False) -> tuple[int, ...]:
        """Gloss every character of ``texts`` the reader cannot yet read.

        The design's writing-system stage, scoped to the card rather than to
        the language: what has to be taught is what a card is about to
        display. The texts given are the ones that reach a card -- the term,
        its headword line, the readings, the example sentences, and the prose
        when the prose is what is shown -- and the answer is the glosses the
        card must come after.

        ``notation`` says the texts are readings rather than language, which
        is what decides how the character's own page is read.
        """
        if not self.teach_script:
            return ()
        found = [
            self.symbol(character, notation=notation)
            for character in script.foreign("\n".join(texts), self.familiar)
        ]
        return tuple(index for index in found if index is not None)

    def symbol(self, character: str, *, notation: bool = False) -> int | None:
        """The gloss that teaches one character, making it if there is none.

        A character the text already teaches as a word of its own is that
        word's gloss: the reader has met the shape, which is all a dependency
        here asserts. It is what keeps a Chinese deck from carrying a symbol
        card behind every word card.
        """
        if character in self.symbols:
            return self.symbols[character]
        if character in self.pending:
            return None
        if (word := self.by_surface.get(character)) is not None:
            self.symbols[character] = word
            return word
        self.pending.add(character)
        try:
            index = self._teach(character, notation=notation)
        finally:
            self.pending.discard(character)
        self.symbols[character] = index
        return index

    def _teach(self, character: str, *, notation: bool = False) -> int | None:
        """Append the gloss for one character.

        Wiktionary first, as everything else here is: the target language's
        own section when it has one -- `ж` is *the eighth letter of the
        Russian alphabet*, with `[ʐ]` and a recording -- and
        :data:`TRANSLINGUAL` when it does not, which is where the IPA symbols,
        the punctuation and the Han characters are written. Only the parts of
        speech in :data:`SHAPE_PARTS` and :data:`NOTATION_PARTS`: a page is
        asked about the shape, and the word that happens to be spelled with it
        is a different card that the text will ask for itself if it uses it.

        Which of the two a character is asked about is settled the first time
        it is met and kept: a glyph is one card whether the text or a reading
        showed it first.
        """
        entry, sense = self._symbol_entry(character, notation=notation)
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
        readings = entry[1].ipa if entry else ()
        if page is not None and not readings:
            readings = page.ipa
        recordings = entry[1].audio_urls if entry else ()
        if page is not None and not recordings:
            recordings = page.audio_urls
        #: The card's own text, read before it exists: a letter is defined in
        #: its own alphabet and pronounced in symbols of another, and neither
        #: may reach the reader unread. :attr:`pending` is what stops the
        #: alphabet from depending on itself.
        depends_on = _merge(
            self.symbols_of(*readings, notation=True),
            self.symbols_of(*self.shown(definition)),
        )
        index = len(self.glosses)
        self.glosses.append(
            Gloss(
                index=index,
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
                depends_on=depends_on,
                key=gloss_key(*key),
                #: No production pair, by the design's rule: only a word
                #: definition gets one. "Given *voiceless palatoalveolar
                #: sibilant*, write the symbol" is a phonetics exercise, and
                #: the half of a script worth drilling in that direction --
                #: writing it -- is not something a deck can mark.
                production=False,
                attribution="" if sense else SYMBOL_ATTRIBUTION,
            )
        )
        self.seen[key] = index
        self.symbol_count += 1
        log(f"[decker]   script: {shown} ({definition[:60]})",
            level=DETAIL, kind="detail")
        return index

    def _symbol_entry(
        self, character: str, *, notation: bool
    ) -> tuple[tuple[Page, Entry] | None, Sense | None]:
        """The entry and sense that talk about the character itself.

        The language's own section is asked first for a character met in the
        text -- it is the section written about this language's writing -- and
        the Translingual one first for a character met in a reading, that
        being where the notation is defined. What each section is allowed to
        answer with differs in the same way, and :data:`NOTATION_PARTS` says
        why.
        """
        if notation:
            asked = (
                (self.translingual_page(character), NOTATION_PARTS + SHAPE_PARTS),
                (self.page(character), NOTATION_PARTS + SHAPE_PARTS),
            )
        else:
            asked = (
                (self.page(character), SHAPE_PARTS + NOTATION_PARTS),
                (self.translingual_page(character), SHAPE_PARTS),
            )
        for page, parts in asked:
            if page is None:
                continue
            for part in parts:
                for entry in page.entries:
                    if entry.part_of_speech == part and entry.senses:
                        return (page, entry), entry.senses[0]
        return None, None

    def translingual_page(self, character: str) -> Page | None:
        """The character's page, cut to the section no language claims."""
        if character not in self.translingual:
            self.translingual[character] = pages.fetch(
                character, edition=self.edition, lang=TRANSLINGUAL,
                refresh=self.refresh,
            )
        return self.translingual[character]

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
            return None
        #: A glossary entry is prose about grammar and quotes the languages it
        #: is explaining -- the entry for *dative* shows German -- so it is
        #: read for symbols like any other card's text.
        depends_on = self.symbols_of(*self.shown(surface, concept.description))
        index = len(self.glosses)
        self.glosses.append(
            Gloss(
                index=index,
                surface=surface,
                #: Its own title: a concept has no inflected and lemmatized
                #: form to tell apart, and printing one under the other would
                #: only say the same thing twice.
                lemma=surface,
                entry=pages.GLOSSARY_PAGE,
                definition=concept.description,
                #: What the text is *about* is grammar, not a language, but
                #: this field is read by the translator as the language a card
                #: teaches, and that is the run's target whatever the card
                #: carries. Where the entry is linked from, the anchor below
                #: answers instead.
                language=name_of(self.lang),
                anchor=concept.anchor,
                depends_on=depends_on,
                key=gloss_key(*key),
                production=False,
            )
        )
        self.seen[key] = index
        self.concept_count += 1
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
            return None
        #: The word is the one thing on this card that is not the model's
        #: prose, and it is the half in a script the reader may not have: a
        #: misspelling and a foreign word are both spelled in the text's own
        #: writing system.
        depends_on = self.symbols_of(surface, *self.shown(explanation))
        index = len(self.glosses)
        self.glosses.append(
            Gloss(
                index=index,
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
            return None
        #: The title carries the representative word, which is a word of the
        #: language and written in its script, and the rule's prose quotes
        #: endings in it throughout.
        depends_on = _merge(
            depends_on, self.symbols_of(surface, *self.shown(rule.description))
        )
        index = len(self.glosses)
        self.glosses.append(
            Gloss(
                index=index,
                surface=surface,
                #: Its own title, as a concept's is: a rule has no inflected
                #: form and no lemma of its own.
                lemma=surface,
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
    rules: bool = True,
    unknowns: str = "fix",
    refresh: bool = False,
    refresh_answers: bool = False,
    known: frozenset[str] = frozenset(),
    teach_script: bool = False,
    mother_lang: str = "en",
    translate: bool = True,
) -> list[Gloss]:
    """Turn term extraction's output into the design's list of glosses."""
    familiar = script.familiar(mother_lang) if teach_script else frozenset()
    if teach_script and familiar is None:
        #: The stage stands down rather than guessing at a repertoire: an
        #: alphabet decker made up would teach a reader letters they have
        #: written all their life, or leave out the ones they have not.
        log(
            f"[decker] --teach-script does not know which characters a reader "
            f"of {name_of(mother_lang)} already reads, so nothing is taught "
            "about the script (decker.script._ALPHABETS is where one goes)",
            kind="warn",
        )
        teach_script = False
        familiar = frozenset()
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
        refresh=refresh,
        known=known,
        teach_script=teach_script,
        familiar=familiar,
        #: The prose on a card is the edition's until the translator has been
        #: over it. Scanning it is right when it stays that way and wrong when
        #: it does not: an English definition on its way to becoming a German
        #: one is not something the reader is ever shown.
        prose=not translate or mother_lang == edition,
    )
    with console.phase("glossing", sum(len(one.text) for one in sentences)):
        for position, sentence in enumerate(sentences):
            if console.skipping():
                #: What is glossed is glossed; the deck is built from it and
                #: the run carries on to the cards.
                break
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
    if builder.symbol_count:
        log(
            f"[decker] {builder.symbol_count} of them are symbols: every "
            "character the cards display is taught by one of them first"
        )
    elif teach_script:
        #: Nothing foreign was found, which for a Latin-script language read
        #: by a reader of English is a real answer and not a failure -- and an
        #: unexpected one often enough to be worth a line.
        log("[decker] nothing on the cards is outside the mother tongue's own "
            "characters; --teach-script added nothing")
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
    surface = _spelling(term, page)
    for sense in senses:
        #: Before anything decides whether this occurrence keeps a card of its
        #: own: what a form-of definition points at is glossed either way. The
        #: design's culling drops the instance and keeps the base word, which
        #: is only a sentence away from being the opposite by accident.
        depends_on = _referenced(
            builder, page, sense, marked, frozenset({page.title})
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
        log(f"[decker] {term.surface!r}: {added} gloss"
            f"{'' if added == 1 else 'es'}", level=VERBOSE, kind="found")
    else:
        log(f"[decker] {term.surface!r}: nothing new to teach",
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
            f"[decker] no {builder.lang} entry for {term.surface!r} "
            f"({', '.join(term.entries)})",
            level=VERBOSE, kind="missing",
        )
        return

    marked = mark_occurrence(sentence, term.spans)
    passage = " ".join(part for part in (around[0], marked, around[1]) if part)
    verdict = unknowns.verdict(term.surface, passage, name_of(builder.lang))
    if verdict is None:
        log(
            f"[decker] no {builder.lang} entry for {term.surface!r}; the model "
            "would not say what it is",
            level=VERBOSE, kind="missing",
        )
        return

    if verdict.is_correction:
        page = builder.page(verdict.correction)
        if page is None or not page.senses:
            log(
                f"[decker] {term.surface!r} looks like {verdict.correction!r}, "
                "which has no entry either",
                level=VERBOSE, kind="missing",
            )
            return
        log(
            f"[decker] {term.surface!r} -> {verdict.correction!r} (spelling)",
            level=VERBOSE, kind="fixed",
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
                f"[decker] {term.surface!r} is a {name_of(builder.lang)} word "
                "Wiktionary lacks; explained by the model",
                level=VERBOSE, kind="fixed",
            )
        return

    if verdict.kind == "foreign":
        if verdict.widely_known and not unknowns.teaches_known_foreign():
            log(
                f"[decker] {term.surface!r} is foreign and widely known; no card",
                level=VERBOSE, kind="dropped",
            )
            return
        if not verdict.explanation:
            return
        index = builder.add_unknown(term.surface, verdict.explanation, unknowns.model)
        if index is not None:
            log(
                f"[decker] {term.surface!r} taught as a foreign word",
                level=VERBOSE, kind="detail",
            )
        return

    log(
        f"[decker] {term.surface!r} is nothing recognizable; dropped",
        level=VERBOSE, kind="dropped",
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
    dependencies = []
    for title in builder.references_of(page).get(sense.definition, ()):
        if title in chain:
            continue
        target = builder.page(title)
        if target is None:
            continue
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
            continue
        #: A dependency the previous deck already teaches comes back as
        #: nothing, and is simply not depended upon: the learner has met it.
        dependencies.append(
            builder.add(
                target,
                surface=title,
                lemma=title,
                sense=kept[0],
                depends_on=_referenced(
                    builder, target, kept[0], marked, chain | {title}
                ),
            )
        )
    return tuple(index for index in dependencies if index is not None)


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
    kept = builder.disambiguator.keep(
        tuple(sense for _, _, sense in labelled),
        sentence=sentence,
        surface=term.surface,
        title=", ".join(f'"{page.title}"' for page in candidates),
        language=candidates[0].language,
        parts_of_speech=tuple(part for _, part, _ in labelled),
        sources=tuple(page.title for page, _, _ in labelled),
        upos=term.upos,
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


def _spelling(term: Term, page: Page) -> str:
    """The term's form, spelled the way Wiktionary spells the entry it won.

    Whatever matched is what the card is fronted with, as long as it is one of
    the term's own spellings. The capital was the first case -- `Cuando`
    glossed from `cuando` is one thing to learn rather than two -- and the
    bound morpheme is the second: a clitic that won its entry at `ל־` is
    fronted `ל־`, with the maqaf, because that is what the dictionary calls
    the thing the card teaches and the maqaf is the part that says it attaches
    to the next word. Bru's call, 2026-09-15.

    Where the entry is a different word -- `enrulada` glossed from `enrulado`,
    for want of a page of its own -- the form the text uses is kept, since the
    entry's is not the term.
    """
    if page.title in term.spellings or term.surface.lower() == page.title.lower():
        return page.title
    return term.surface

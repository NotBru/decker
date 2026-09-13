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

import hashlib
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from decker import pages
from decker.disambiguation import Disambiguator
from decker.languages import name_of
from decker.morphology import Morphology, Outcome, Rule, label_of
from decker.ollama import default_model
from decker.pages import Concept, Example, Page, Sense
from decker.terms import Term

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
            self.fetched[title] = pages.fetch(
                title, edition=self.edition, lang=self.lang, refresh=self.refresh
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
        #: exactly what a dependency says.
        depends_on = _merge(depends_on, self.concepts_of(sense))
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
                etymology=page.etymology,
                ipa=page.ipa,
                audio_urls=page.audio_urls,
                audios=self._audios(page),
                depends_on=depends_on,
                key=gloss_key(surface, sense.definition),
            )
        )
        self.seen[key] = index
        return index

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
            print(
                f"[decker] could not read {pages.GLOSSARY_PAGE} and none is "
                "cached; no concept cards this run",
                file=sys.stderr,
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
                key=gloss_key(*key),
                production=False,
            )
        )
        self.seen[key] = index
        self.concept_count += 1
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

    def _audios(self, page: Page) -> tuple[str, ...]:
        """Every recording of the page, downloaded, minus the ones that failed."""
        if not self.audio:
            return ()
        if not pages.carries_media(page.source):
            self.silent.add(page.title)
            return ()
        self.offered += len(page.audio_urls)
        paths = (pages.audio_path(url) for url in page.audio_urls)
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
    refresh: bool = False,
    refresh_answers: bool = False,
    known: frozenset[str] = frozenset(),
) -> list[Gloss]:
    """Turn term extraction's output into the design's list of glosses."""
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
    )
    builder = _Builder(
        edition=edition,
        lang=target_lang,
        disambiguator=disambiguator,
        morphology=morphology,
        audio=audio,
        concepts=concepts,
        refresh=refresh,
        known=known,
    )
    for sentence in sentences:
        for term in sentence.terms:
            _gloss_term(builder, term, sentence.text)
    if audio and builder.glosses and not builder.offered:
        #: A source that carries no media at all is not the same as a word
        #: that happens to have no recording, and the two look identical on
        #: a card. A local mirror is the ordinary reason: media is in no dump.
        print(
            "[decker] no recordings offered by this source; cards will have no "
            "audio (a local Wiktionary carries none: media is in no dump)",
            file=sys.stderr,
        )
    elif audio and builder.silent:
        #: The mixed case, which the cache now makes ordinary: some pages were
        #: read from a mirror's cache entry and some from Wikimedia's, so the
        #: deck has audio on most cards and none on these, for a reason that
        #: has nothing to do with the words.
        count = len(builder.silent)
        print(
            f"[decker] {count} page{'' if count == 1 else 's'} came from a "
            "source with no media; those cards have no audio (--refresh-pages "
            "against Wikimedia gets it, at the cost of naming them to it)",
            file=sys.stderr,
        )
    if builder.skipped:
        print(
            f"[decker] {builder.skipped} glosses already taught, left out",
            file=sys.stderr,
        )
    if builder.unresolved:
        #: An anchor the glossary has no entry for is terminology decker can
        #: see and cannot explain, so it is counted rather than guessed at.
        total = sum(builder.unresolved.values())
        names = ", ".join(anchor for anchor, _ in builder.unresolved.most_common(5))
        print(
            f"[decker] {total} links to glossary entries that do not exist "
            f"({len(builder.unresolved)} distinct: {names}); no cards for those",
            file=sys.stderr,
        )
    if builder.concept_count:
        print(
            f"[decker] {builder.concept_count} of them are concepts "
            f"({pages.GLOSSARY_PAGE})",
            file=sys.stderr,
        )
    morphology.report()
    print(f"[decker] {len(builder.glosses)} glosses", file=sys.stderr)
    return builder.glosses


def _gloss_term(builder: _Builder, term: Term, sentence: str) -> None:
    candidates = builder.own_pages(term) or [
        page for page in (builder.first_page(term.entries),) if page is not None
    ]
    if not candidates:
        print(
            f"[decker] no {builder.lang} entry for {term.surface!r} "
            f"({', '.join(term.entries)})",
            file=sys.stderr,
        )
        return

    marked = mark_occurrence(sentence, term.spans)
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
            if targets := _targets(sense.definition, page.title):
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
    )
    surviving = {id(sense) for sense in kept}
    chosen = [(page, sense) for page, _, sense in labelled if id(sense) in surviving]
    if not chosen:
        return candidates[0], ()

    counts = Counter(page.title for page, _ in chosen)
    winner = max(candidates, key=lambda page: (counts[page.title], -candidates.index(page)))
    dropped = [title for title in counts if title != winner.title]
    if dropped:
        print(
            f"[decker] {term.surface!r}: kept senses from {winner.title!r}, "
            f"dropping those from {', '.join(repr(t) for t in dropped)}",
            file=sys.stderr,
        )
    return winner, tuple(sense for page, sense in chosen if page.title == winner.title)


def _spelling(term: Term, page: Page) -> str:
    """The term's form, spelled the way Wiktionary spells the entry it won.

    Only the capital is at stake: where the entry is the same word, its
    spelling is taken whole, so `Cuando` glossed from `cuando` is one thing to
    learn rather than two. Where the entry is a different word -- `enrulada`
    glossed from `enrulado`, for want of a page of its own -- the form the
    text uses is kept, since the entry's is not the term.
    """
    if term.surface.lower() == page.title.lower():
        return page.title
    return term.surface

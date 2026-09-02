"""Definition fetching: from terms to glosses.

One gloss per term, plus one for the lemma whenever the term is inflected and
Wiktionary spells the lemma under a page of its own. The inflected gloss
depends on the lemma's, and its definition is the form-of line Wiktionary
already writes -- "third-person singular preterite indicative of correr" --
which is exactly the relationship the design asks the inflected gloss to
explain. Glosses appear in the order their terms occur in the source, a
dependency always before what depends on it.
"""

from __future__ import annotations

import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from decker import pages
from decker.disambiguation import Disambiguator
from decker.ollama import default_model
from decker.pages import Example, Page, Sense
from decker.terms import Term

if TYPE_CHECKING:
    from decker.pipeline import SentenceTerms


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


@dataclass
class _Builder:
    """Accumulates glosses, keeping them unique and ordered."""

    edition: str
    lang: str
    disambiguator: Disambiguator
    audio: bool = True
    refresh: bool = False
    glosses: list[Gloss] = field(default_factory=list)
    #: Inflected form and sense, the design's identity for a gloss.
    seen: dict[tuple[str, str], int] = field(default_factory=dict)
    #: Pages already looked up this run, misses included.
    fetched: dict[str, Page | None] = field(default_factory=dict)
    #: Per page, which of its definitions describe it in terms of what.
    refs: dict[str, dict[str, tuple[str, ...]]] = field(default_factory=dict)

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
    ) -> int:
        """Append a gloss, or return the index of the one already standing."""
        key = (surface, sense.definition)
        if key in self.seen:
            return self.seen[key]
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
            )
        )
        self.seen[key] = index
        return index

    def _audios(self, page: Page) -> tuple[str, ...]:
        """Every recording of the page, downloaded, minus the ones that failed."""
        if not self.audio:
            return ()
        paths = (pages.audio_path(url) for url in page.audio_urls)
        return tuple(str(path) for path in paths if path)


def build(
    sentences: list["SentenceTerms"],
    *,
    target_lang: str,
    edition: str,
    model: str | None = None,
    host: str | None = None,
    disambiguate: bool = True,
    audio: bool = True,
    refresh: bool = False,
) -> list[Gloss]:
    """Turn term extraction's output into the design's list of glosses."""
    disambiguator = Disambiguator(
        model=model or default_model(), host=host, enabled=disambiguate
    )
    builder = _Builder(
        edition=edition,
        lang=target_lang,
        disambiguator=disambiguator,
        audio=audio,
        refresh=refresh,
    )
    for sentence in sentences:
        for term in sentence.terms:
            _gloss_term(builder, term, sentence.text)
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
        builder.add(
            page,
            surface=surface,
            lemma=term.lemma,
            sense=sense,
            depends_on=_referenced(builder, page, sense, marked, frozenset({page.title})),
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
    return tuple(dependencies)


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

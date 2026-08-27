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

import sys
from collections import Counter
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from decker import pages
from decker.disambiguation import DEFAULT_MODEL, Disambiguator
from decker.pages import Page, Sense
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
    examples: tuple[str, ...] = ()
    etymology: str | None = None
    ipa: tuple[str, ...] = ()
    #: Wiktionary's sound file for the entry, if it has one. Kept whether or
    #: not the file itself was downloaded: a document wants the link.
    audio_url: str | None = None
    #: Cached sound file, if Wiktionary had one and audio was not turned off.
    audio: str | None = None
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
                audio_url=page.audio_url,
                audio=self._audio(page),
                depends_on=depends_on,
            )
        )
        self.seen[key] = index
        return index

    def add_all(
        self,
        page: Page,
        *,
        surface: str,
        lemma: str,
        senses: tuple[Sense, ...],
        depends_on: tuple[int, ...] = (),
    ) -> tuple[int, ...]:
        """One gloss per sense, in the order the page lists them."""
        return tuple(
            self.add(
                page,
                surface=surface,
                lemma=lemma,
                sense=sense,
                depends_on=depends_on,
            )
            for sense in senses
        )

    def _audio(self, page: Page) -> str | None:
        if not self.audio or page.audio_url is None:
            return None
        path = pages.audio_path(page.audio_url)
        return str(path) if path else None


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
        model=model or DEFAULT_MODEL, host=host, enabled=disambiguate
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
    depends_on: tuple[int, ...] = ()
    if term.lemma != surface and term.lemma != page.title:
        lemma_page = builder.page(term.lemma)
        if lemma_page is not None:
            #: Every surviving sense of the lemma is a dependency: the form-of
            #: line names the lemma, not one of its meanings, so the word has
            #: to be known before the inflection of it can be.
            depends_on = builder.add_all(
                lemma_page,
                surface=term.lemma,
                lemma=term.lemma,
                senses=_senses(builder, lemma_page, term.lemma, term.lemma, marked),
            )

    builder.add_all(
        page,
        surface=surface,
        lemma=term.lemma,
        senses=senses,
        depends_on=depends_on,
    )


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


def _senses(
    builder: _Builder, page: Page, surface: str, lemma: str, sentence: str
) -> tuple[Sense, ...]:
    """The senses of ``page`` that this occurrence actually uses."""
    labelled = page.senses
    return builder.disambiguator.keep(
        tuple(sense for _, sense in labelled),
        sentence=sentence,
        surface=surface,
        title=page.title,
        language=page.language,
        parts_of_speech=tuple(part for part, _ in labelled),
    )

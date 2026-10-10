"""The v1 pipeline, from source text to a shuffled deck of cards.

Source format normalization is omitted in v1: the input is already text.
Sentencing and term extraction share Stanza's parse of the document,
definition fetching turns the terms they produce into glosses, and deck
construction and shuffling turn those into the cards Anki is handed. Each
function here stops the pipeline one stage further along.
"""

from __future__ import annotations

import dataclasses
import sys
import time
from dataclasses import dataclass

from decker import cards as deck_cards
from decker import pages, reach
from decker import shuffling, trees, wiktionary
from decker import strokes as strokes_
from decker.cards import Card
from decker.console import VERBOSE, console, log
from decker.glosses import Gloss
from decker.glosses import build as build_glosses
from decker.languages import respellings, unspaced
from decker.nlp import pipeline
from decker.terms import Term, extract
from decker.translation import SOURCE_LANG
from decker.wiktionary import TitleIndex

#: v1 assumes English as the mother language, so glosses -- and therefore the
#: titles a term has to be one of -- come from the English Wiktionary, which
#: carries entries for every language and not just its own.
MOTHER_EDITION = "en"


@dataclass(frozen=True)
class SentenceTerms:
    """One sentence of the source, and the terms it is made of."""

    text: str
    terms: list[Term]
    #: Where the sentence starts in the text the parser was given, so a stage
    #: that knows something about the source's own shape -- a cue file's
    #: clock -- can say where in it this sentence was. -1 when the parse did
    #: not offer one, which is a tokenizer without character offsets rather
    #: than anything about the sentence.
    start: int = -1


def run(
    text: str,
    *,
    target_lang: str,
    edition: str | None = None,
    whole_index: bool = False,
    refresh_titles: bool = False,
) -> list[SentenceTerms]:
    """Run the v1 pipeline over ``text`` up to term extraction."""
    parser = pipeline(target_lang)
    #: The parse is one call over the whole document and cannot report its way
    #: through, so the only honest thing is to say it has started and how much
    #: it was given. It is also where a run's memory goes: a series' worth of
    #: subtitles is megabytes of text held as trees.
    log(f"[decker] parsing {len(text)} characters", kind="head")
    started = time.monotonic()
    document = parser(text)
    sentences = document.sentences
    log(f"[decker] {len(sentences)} sentences in "
        f"{time.monotonic() - started:.1f}s", kind="head")

    join_particles = trees.joins_particles(target_lang)
    vocabulary = None
    if not whole_index:
        log("[decker] collecting the text's vocabulary", level=VERBOSE)
        #: With the respellings, or the filter throws away the very titles
        #: they were generated to reach: `грёз` is not a spelling the text
        #: has, and an index built from the text alone would not keep it.
        vocabulary = wiktionary.vocabulary_of(
            tree
            for sentence in sentences
            for tree in trees.sentence_tree(
                sentence,
                join_particles=join_particles,
                respell=lambda label: respellings(label, target_lang),
            )
        )
        log(f"[decker] {len(vocabulary)} distinct spellings to look for",
            level=VERBOSE)
    #: A language written without spaces has titles without them too, and a
    #: compound among them is reachable only through the runs of tokens it is
    #: written as; see `wiktionary.build_index`.
    runs = (
        wiktionary.runs_of(sentences)
        if vocabulary is not None and unspaced(target_lang)
        else None
    )
    index = build_index(
        target_lang,
        edition=edition,
        vocabulary=vocabulary,
        runs=runs,
        refresh_titles=refresh_titles,
    )
    #: Term extraction is fast per sentence and slow over a series, and it is
    #: the last stage before the one that talks to the network, so a bar here
    #: is the difference between "it is working" and "it is stuck on the
    #: index".
    found = []
    with console.phase(
        "terms",
        sum(len(one.text) for one in sentences),
        unit="characters",
        items=len(sentences),
    ):
        for sentence in sentences:
            if console.skipping():
                break
            found.append(
                SentenceTerms(
                    text=sentence.text,
                    terms=extract(
                        sentence, index, join_particles=join_particles,
                        lang=target_lang,
                    ),
                    start=_start_of(sentence),
                )
            )
            console.advance(len(sentence.text))
    log(f"[decker] {sum(len(one.terms) for one in found)} terms", kind="head")
    return found


def _start_of(sentence) -> int:
    """Where a parsed sentence begins in the document, by character."""
    tokens = getattr(sentence, "tokens", None)
    start = getattr(tokens[0], "start_char", None) if tokens else None
    return -1 if start is None else int(start)


def define(
    text: str,
    *,
    target_lang: str,
    edition: str | None = None,
    whole_index: bool = False,
    refresh_titles: bool = False,
    model: str | None = None,
    host: str | None = None,
    disambiguate: bool = True,
    audio: bool = True,
    concepts: bool = True,
    components: bool = True,
    rules: bool = True,
    unknowns: str = "fix",
    refresh_pages: bool = False,
    refresh_answers: bool = False,
    known: frozenset[str] = frozenset(),
    teach_script: bool = False,
    mother_lang: str = SOURCE_LANG,
    limit_glosses: int = 0,
) -> list[Gloss]:
    """Run the v1 pipeline the whole way, from text to glosses."""
    return glossed(
        text,
        target_lang=target_lang,
        edition=edition,
        whole_index=whole_index,
        refresh_titles=refresh_titles,
        model=model,
        host=host,
        disambiguate=disambiguate,
        audio=audio,
        concepts=concepts,
        components=components,
        rules=rules,
        unknowns=unknowns,
        refresh_pages=refresh_pages,
        refresh_answers=refresh_answers,
        known=known,
        teach_script=teach_script,
        mother_lang=mother_lang,
        limit_glosses=limit_glosses,
    )[1]


def glossed(
    text: str,
    *,
    target_lang: str,
    edition: str | None = None,
    whole_index: bool = False,
    refresh_titles: bool = False,
    model: str | None = None,
    host: str | None = None,
    disambiguate: bool = True,
    audio: bool = True,
    concepts: bool = True,
    components: bool = True,
    rules: bool = True,
    unknowns: str = "fix",
    refresh_pages: bool = False,
    refresh_answers: bool = False,
    known: frozenset[str] = frozenset(),
    teach_script: bool = False,
    mother_lang: str = SOURCE_LANG,
    limit_glosses: int = 0,
) -> tuple[list[SentenceTerms], list[Gloss]]:
    """The same run, keeping the sentences the glosses were made from.

    :func:`define` is this and its second half. The sentences are what a
    caller needs to say *where* a gloss came from, which the glosses
    themselves record only as an index into this list.
    """
    sentences = run(
        text,
        target_lang=target_lang,
        edition=edition,
        whole_index=whole_index,
        refresh_titles=refresh_titles,
    )
    glosses = build_glosses(
        sentences,
        target_lang=target_lang,
        edition=edition or MOTHER_EDITION,
        model=model,
        host=host,
        disambiguate=disambiguate,
        audio=audio,
        concepts=concepts,
        components=components,
        rules=rules,
        unknowns=unknowns,
        refresh=refresh_pages,
        refresh_answers=refresh_answers,
        known=known,
        #: Which scripts the reader already reads is a question about the
        #: mother tongue, so deck construction's flag is needed one stage
        #: earlier than deck construction.
        teach_script=teach_script,
        mother_lang=mother_lang,
        #: The stage stops itself rather than the walk being cut short here:
        #: a term's glosses are made together -- its senses, the characters it
        #: is written in, the terms it is composed of -- and a list cut at an
        #: exact number would be cut inside one of those.
        limit=limit_glosses,
    )
    pages.report()
    reach.report()
    return sentences, glosses


def deck(
    text: str,
    *,
    target_lang: str,
    mother_lang: str = SOURCE_LANG,
    seed: int | None = None,
    window: int = shuffling.WINDOW,
    translate: bool = True,
    strokes: bool = True,
    **define_arguments,
) -> list[Card]:
    """Run every stage: text, terms, glosses, cards, and the order to learn them."""
    glosses = define(
        text, target_lang=target_lang, mother_lang=mother_lang, **define_arguments
    )
    built = deck_cards.build(
        glosses,
        mother_lang=mother_lang,
        model=define_arguments.get("model"),
        host=define_arguments.get("host"),
        translate=translate,
        refresh_answers=define_arguments.get("refresh_answers", False),
    )
    if strokes:
        built = _with_strokes(built, glosses, target_lang)
    return shuffling.shuffle(built, seed=seed, window=window)


def _with_strokes(
    cards: list[Card], glosses: list[Gloss], target_lang: str
) -> list[Card]:
    """Every card whose term is one character, with that character's strokes.

    Read off the gloss rather than the card: a recognition card's front may be
    `Symbol: 所` or a word marked with its sense, and the gloss knows which
    character it is. A title decker wrote -- a concept, a rule -- is prose and
    never a character, whatever its length.
    """
    drawn: dict[int, str] = {}
    for gloss in glosses:
        if gloss.title_prose:
            continue
        character = gloss.surface.removeprefix(gloss.title_prefix)
        if path := strokes_.drawn(character, target_lang):
            drawn[gloss.index] = path
    if drawn:
        log(f"[decker] {len(drawn)} characters drawn with their stroke order",
            kind="head")
    return [
        dataclasses.replace(
            card, answer=dataclasses.replace(card.answer, strokes=drawn[card.gloss])
        )
        if card.gloss in drawn
        else card
        for card in cards
    ]


def build_index(
    target_lang: str,
    *,
    edition: str | None = None,
    vocabulary: set[str] | None = None,
    runs: set[str] | None = None,
    refresh_titles: bool = False,
) -> TitleIndex:
    """Build the title index, parsing its titles as ``target_lang``."""
    return wiktionary.build_index(
        edition or MOTHER_EDITION,
        lang=target_lang,
        vocabulary=vocabulary,
        runs=runs,
        refresh=refresh_titles,
    )

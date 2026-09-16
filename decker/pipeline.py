"""The v1 pipeline, from source text to a shuffled deck of cards.

Source format normalization is omitted in v1: the input is already text.
Sentencing and term extraction share Stanza's parse of the document,
definition fetching turns the terms they produce into glosses, and deck
construction and shuffling turn those into the cards Anki is handed. Each
function here stops the pipeline one stage further along.
"""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass

from decker import cards as deck_cards
from decker import pages
from decker import shuffling, trees, wiktionary
from decker.cards import Card
from decker.console import VERBOSE, console, log
from decker.glosses import Gloss
from decker.glosses import build as build_glosses
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
        vocabulary = wiktionary.vocabulary_of(
            tree
            for sentence in sentences
            for tree in trees.sentence_tree(sentence, join_particles=join_particles)
        )
        log(f"[decker] {len(vocabulary)} distinct spellings to look for",
            level=VERBOSE)
    index = build_index(
        target_lang,
        edition=edition,
        vocabulary=vocabulary,
        refresh_titles=refresh_titles,
    )
    #: Term extraction is fast per sentence and slow over a series, and it is
    #: the last stage before the one that talks to the network, so a bar here
    #: is the difference between "it is working" and "it is stuck on the
    #: index".
    found = []
    with console.phase("terms", sum(len(one.text) for one in sentences)):
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
                )
            )
            console.advance(len(sentence.text))
    log(f"[decker] {sum(len(one.terms) for one in found)} terms", kind="head")
    return found


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
    rules: bool = True,
    unknowns: str = "fix",
    refresh_pages: bool = False,
    refresh_answers: bool = False,
    known: frozenset[str] = frozenset(),
) -> list[Gloss]:
    """Run the v1 pipeline the whole way, from text to glosses."""
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
        rules=rules,
        unknowns=unknowns,
        refresh=refresh_pages,
        refresh_answers=refresh_answers,
        known=known,
    )
    pages.report()
    return glosses


def deck(
    text: str,
    *,
    target_lang: str,
    mother_lang: str = SOURCE_LANG,
    seed: int | None = None,
    window: int = shuffling.WINDOW,
    translate: bool = True,
    **define_arguments,
) -> list[Card]:
    """Run every stage: text, terms, glosses, cards, and the order to learn them."""
    glosses = define(text, target_lang=target_lang, **define_arguments)
    built = deck_cards.build(
        glosses,
        mother_lang=mother_lang,
        model=define_arguments.get("model"),
        host=define_arguments.get("host"),
        translate=translate,
        refresh_answers=define_arguments.get("refresh_answers", False),
    )
    return shuffling.shuffle(built, seed=seed, window=window)


def build_index(
    target_lang: str,
    *,
    edition: str | None = None,
    vocabulary: set[str] | None = None,
    refresh_titles: bool = False,
) -> TitleIndex:
    """Build the title index, parsing its titles as ``target_lang``."""
    return wiktionary.build_index(
        edition or MOTHER_EDITION,
        lang=target_lang,
        vocabulary=vocabulary,
        refresh=refresh_titles,
    )

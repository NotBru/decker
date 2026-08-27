"""The v1 pipeline, from source text to glosses.

Source format normalization is omitted in v1: the input is already text.
Sentencing and term extraction share Stanza's parse of the document, and
definition fetching turns the terms they produce into glosses.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass

from decker import trees, wiktionary
from decker.glosses import Gloss
from decker.glosses import build as build_glosses
from decker.nlp import pipeline
from decker.terms import Term, extract
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
    document = pipeline(target_lang)(text)
    sentences = document.sentences
    print(f"[decker] {len(sentences)} sentences", file=sys.stderr)

    join_particles = trees.joins_particles(target_lang)
    vocabulary = None
    if not whole_index:
        vocabulary = wiktionary.vocabulary_of(
            tree
            for sentence in sentences
            for tree in trees.sentence_tree(sentence, join_particles=join_particles)
        )
    index = build_index(
        target_lang,
        edition=edition,
        vocabulary=vocabulary,
        refresh_titles=refresh_titles,
    )
    return [
        SentenceTerms(
            text=sentence.text,
            terms=extract(sentence, index, join_particles=join_particles),
        )
        for sentence in sentences
    ]


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
    refresh_pages: bool = False,
) -> list[Gloss]:
    """Run the v1 pipeline the whole way, from text to glosses."""
    sentences = run(
        text,
        target_lang=target_lang,
        edition=edition,
        whole_index=whole_index,
        refresh_titles=refresh_titles,
    )
    return build_glosses(
        sentences,
        target_lang=target_lang,
        edition=edition or MOTHER_EDITION,
        model=model,
        host=host,
        disambiguate=disambiguate,
        audio=audio,
        refresh=refresh_pages,
    )


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

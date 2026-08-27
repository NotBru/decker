"""Stanza pipelines, one per language, loaded lazily and reused."""

from __future__ import annotations

import functools

import stanza

PROCESSORS = "tokenize,pos,lemma,depparse"


@functools.cache
def pipeline(lang: str) -> stanza.Pipeline:
    """Return the UD pipeline for ``lang``, downloading models on first use."""
    return stanza.Pipeline(lang, processors=PROCESSORS, logging_level="WARN")

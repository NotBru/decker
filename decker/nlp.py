"""Stanza pipelines, one per language, loaded lazily and reused."""

from __future__ import annotations

import functools
import time

import stanza

from decker.console import log
from decker.languages import name_of

PROCESSORS = "tokenize,pos,lemma,depparse"


@functools.cache
def pipeline(lang: str) -> stanza.Pipeline:
    """Return the UD pipeline for ``lang``, downloading models on first use.

    Announced, because it is the longest thing a run does before it has
    anything to say: four models off disk is a quiet ten to twenty seconds,
    and a first run for a language downloads them, which is minutes of a
    terminal that looks hung. The line before says what is happening and the
    line after says how long it took, so the next run's pause is expected.
    """
    log(f"[decker] loading the {name_of(lang)} parser ({PROCESSORS})", kind="head")
    started = time.monotonic()
    loaded = stanza.Pipeline(lang, processors=PROCESSORS, logging_level="WARN")
    log(f"[decker] parser ready in {time.monotonic() - started:.1f}s", kind="detail")
    return loaded

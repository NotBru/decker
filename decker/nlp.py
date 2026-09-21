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
    #: The models are on disk after the first run; the *index* of them is what
    #: Stanza re-downloads on every `Pipeline`, so an ordinary run reaches
    #: `raw.githubusercontent.com` (or `$STANZA_RESOURCES_URL`) before it
    #: parses a word it already knows how to parse -- and dies there when the
    #: name does not resolve, which took three runs down on 2026-09-17 with
    #: every model it needed sitting in the cache. `REUSE_RESOURCES` keeps the
    #: index that is already there and still downloads a model that is
    #: missing, so a first run for a language is unchanged and every run after
    #: it is offline.
    loaded = stanza.Pipeline(
        lang,
        processors=PROCESSORS,
        logging_level="WARN",
        download_method=stanza.DownloadMethod.REUSE_RESOURCES,
    )
    log(f"[decker] parser ready in {time.monotonic() - started:.1f}s", kind="detail")
    return loaded

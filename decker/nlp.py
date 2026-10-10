"""Stanza pipelines, one per language, loaded lazily and reused.

Stanza tags and parses every language decker reads. Japanese is the one whose
words it does not also cut: its tokenizer and lemmatizer were trained on
edited prose, and a manga's speech is not that -- `撮られん` came out as the
lemma `取る`, `太んなくて` as `太ぶ`, `いんなら` as `言う`. Sudachi, a
dictionary-driven analyzer, cuts the text and names each word's dictionary
form instead, and Stanza tags and parses what it cut. The measurements and the
choices are in `docs/execution/term-extraction.md`.
"""

from __future__ import annotations

import functools
import re
import time
import unicodedata
from collections.abc import Iterator
from typing import Any

import stanza
from stanza.models.common import doc
from stanza.pipeline._constants import TOKENIZE
from stanza.pipeline.processor import ProcessorVariant, register_processor_variant

from decker.console import log
from decker.languages import name_of

PROCESSORS = "tokenize,pos,lemma,depparse"

#: Languages whose text is cut by a dictionary rather than by Stanza, and the
#: name the cut goes by -- which is also part of the name a parsed title is
#: cached under, since a title's tree only matches a sentence cut the same way.
_CUTTERS = {"ja": "sudachi"}


def parser_tag(lang: str) -> str:
    """The name of the tokenizer ``lang`` is cut with, if not Stanza's own."""
    return _CUTTERS.get(lang, "")


@functools.cache
def pipeline(lang: str) -> Any:
    """Return the UD pipeline for ``lang``, downloading models on first use.

    Announced, because it is the longest thing a run does before it has
    anything to say: four models off disk is a quiet ten to twenty seconds,
    and a first run for a language downloads them, which is minutes of a
    terminal that looks hung. The line before says what is happening and the
    line after says how long it took, so the next run's pause is expected.
    """
    cutter = parser_tag(lang)
    log(
        f"[decker] loading the {name_of(lang)} parser ({PROCESSORS}"
        f"{f', cut by {cutter}' if cutter else ''})",
        kind="head",
    )
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
    options: dict[str, Any] = {}
    if cutter:
        options["tokenize_with_" + _VARIANT] = True
    loaded = stanza.Pipeline(
        lang,
        processors=PROCESSORS,
        logging_level="WARN",
        download_method=stanza.DownloadMethod.REUSE_RESOURCES,
        **options,
    )
    if cutter:
        loaded = _DictionaryLemmas(loaded)
    log(f"[decker] parser ready in {time.monotonic() - started:.1f}s", kind="detail")
    return loaded


#: The name decker's Sudachi tokenizer is registered with Stanza under. Not
#: Stanza's own `sudachipy` variant, which cuts at Sudachi's longest units and
#: ends a sentence only at `。！？` -- a manga's speech bubbles are separated by
#: blank lines and rarely punctuated, so a volume came out as one sentence.
_VARIANT = "decker_sudachi"

#: Sudachi refuses an input over 49,149 bytes, so the text is handed over a
#: line at a time and a line longer than this is cut where a sentence ends.
_CHUNK_BYTES = 40_000

#: Where a sentence ends: the punctuation that closes one, and a blank line.
_FINAL = frozenset("。！？!?‼⁉")
#: What may follow a sentence's final mark and still belong to it.
_CLOSERS = frozenset("」』）)】〕〉》\"'”’")


@functools.cache
def _sudachi() -> Any:
    from sudachipy import Dictionary

    return Dictionary(dict="core").tokenizer()


def _morphemes(text: str) -> Iterator[tuple[int, int, str, str | None]]:
    """Sudachi's words of ``text``: start, end, surface and dictionary form.

    The form is ``None`` for a symbol -- Sudachi's `補助記号`, the brackets,
    stops and marks, and anything else without a letter or a digit in it,
    since it calls `‼︎` a common noun -- which it otherwise normalises to a
    half-width one the text never wrote: `！` would be looked up as `!`.

    The shortest unit (split mode A), because a compound the dictionary has a
    page for is put back together by the title index -- `事務所` is a phrase
    title over `事務` and `所` -- while one it has no page for, `極楽街`, keeps
    pieces that do. The longest unit would make the second a word with no
    entry at all.
    """
    from sudachipy import SplitMode

    tokenizer = _sudachi()
    for offset, chunk in _chunks(text):
        for morpheme in tokenizer.tokenize(chunk, SplitMode.A):
            surface = morpheme.surface()
            #: Sudachi reads `…` as the three dots it normalises it to, and
            #: hands the two it made up back as words with no text at all;
            #: Stanza refuses a token with none. The manga writes `⋯`, so it
            #: was a benchmark sentence that found this, 2026-10-10.
            if not surface:
                continue
            symbol = morpheme.part_of_speech()[0] == "補助記号" or not any(
                character.isalnum() for character in surface
            )
            yield (
                offset + morpheme.begin(),
                offset + morpheme.end(),
                surface,
                None if symbol else morpheme.dictionary_form(),
            )


def boundaries(text: str, *, read: bool = False) -> list[int]:
    """Where Sudachi's words of ``text`` end, counted in characters.

    With ``read``, counted in the hiragana of each word's reading instead, so a
    kanji spelling can be laid against the kana it is read as: 皆さん ends its
    words at 2 and 4, where `みな` and `さん` do, while 操舵 is one word read
    `そうだ` and ends only at 3.
    """
    from sudachipy import SplitMode

    ends: list[int] = []
    position = 0
    for morpheme in _sudachi().tokenize(text, SplitMode.A):
        position += len(_hiragana(morpheme.reading_form()) if read else morpheme.surface())
        ends.append(position)
    return ends


def _hiragana(text: str) -> str:
    return "".join(
        chr(ord(character) - 0x60) if "\u30a1" <= character <= "\u30f6" else character
        for character in text
    )


def _chunks(text: str) -> Iterator[tuple[int, str]]:
    """``text`` in pieces Sudachi will take, with where each one starts."""
    position = 0
    for line in text.splitlines(keepends=True):
        if len(line.encode("utf-8")) <= _CHUNK_BYTES:
            yield position, line
        else:
            start = 0
            for found in re.finditer(r"[。！？!?‼⁉]+", line):
                if len(line[start : found.end()].encode("utf-8")) > _CHUNK_BYTES:
                    break
            #: A line with no sentence end in reach is cut by characters; a
            #: word split there is a cost of a text with forty thousand bytes
            #: on one line, which nothing decker reads has.
            step = _CHUNK_BYTES // 4
            for start in range(0, len(line), step):
                yield position + start, line[start : start + step]
        position += len(line)


@register_processor_variant(TOKENIZE, _VARIANT)
class _SudachiTokenizer(ProcessorVariant):
    """Cut Japanese with Sudachi, and end sentences where the text does."""

    def __init__(self, config: dict) -> None:
        if config["lang"] != "ja":
            raise ValueError("decker's Sudachi tokenizer is for Japanese only")

    def process(self, document: Any) -> doc.Document:
        text = document.text if isinstance(document, doc.Document) else document
        sentences: list[list[dict]] = []
        current: list[dict] = []
        ending = False
        for start, end, surface, _ in _morphemes(text):
            if surface.isspace():
                #: A blank line is a paragraph's end, and in a manga's text the
                #: end of a speech bubble -- the sentence there is, punctuated
                #: or not.
                if surface.count("\n") >= 2 or "\n\n" in text[start:end + 1]:
                    ending = True
                continue
            closing = ending and bool(current) and (
                surface in _CLOSERS or _attaches(surface)
            )
            if ending and not closing:
                if current:
                    sentences.append(current)
                current = []
            ending = closing
            current.append(
                {
                    doc.TEXT: surface,
                    doc.MISC: f"{doc.START_CHAR}={start}|{doc.END_CHAR}={end}",
                }
            )
            if surface.rstrip("\ufe0e\ufe0f")[-1:] in _FINAL:
                ending = True
        if current:
            sentences.append(current)
        return doc.Document(sentences, text)


def _attaches(surface: str) -> bool:
    """Whether ``surface`` only modifies what precedes it: `‼︎`'s variation
    selector, which Sudachi may hand over on its own."""
    return all(unicodedata.category(character) in ("Mn", "Me", "Cf") for character in surface)


class _DictionaryLemmas:
    """A Stanza pipeline whose lemmas are the dictionary's, not the model's.

    Stanza's lemmatizer runs anyway -- the parser is trained on its output
    being there -- and its answers are then replaced with Sudachi's dictionary
    form for the same span. Sudachi is asked twice for the same text, which is
    milliseconds, and gives the same cut both times.
    """

    def __init__(self, pipeline: stanza.Pipeline) -> None:
        self._pipeline = pipeline

    def __call__(self, text: str) -> doc.Document:
        return self._relemmatized(self._pipeline(text))

    def bulk_process(self, documents: list[doc.Document]) -> list[doc.Document]:
        return [self._relemmatized(one) for one in self._pipeline.bulk_process(documents)]

    @staticmethod
    def _relemmatized(document: doc.Document) -> doc.Document:
        """Sudachi's lemmas put in, and its symbols marked as punctuation.

        The second because Stanza's tagger, handed Sudachi's cut, tagged `！`
        a noun; a symbol is the dictionary's to know, and `PUNCT` is what term
        extraction drops.
        """
        lemmas = {
            (start, end): lemma
            for start, end, _, lemma in _morphemes(document.text)
        }
        for sentence in document.sentences:
            for word in sentence.words:
                token = word.parent
                span = (token.start_char, token.end_char)
                if span not in lemmas:
                    continue
                lemma = lemmas[span]
                if lemma is None:
                    word.lemma = word.text
                    word.upos = "PUNCT"
                else:
                    word.lemma = lemma
        return document

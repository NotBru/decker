"""The order a character is written in, drawn for a card that is one character.

Bru's request of 2026-10-06: wherever a card is a single symbol -- `Symbol: 所`,
the word 人, the kana あ -- its answer shows the character's strokes, numbered
in the order they are written. The order is not the script's but the
language's: 必, 田 and 生 are written differently in Japan, in the PRC and in
Taiwan, so a source is chosen per *target language* and never per character.

Two sources, each one archive downloaded once and read locally, so that what
a text is written in is never asked of a server character by character -- the
same reason a mirror run fetches no audio:

- **Japanese: KanjiVG**, the Japanese stroke-order data every kanji tool
  draws on, kana included, with the numbers already placed. CC BY-SA 3.0.
- **Chinese: Make Me a Hanzi**, outlines and stroke medians for 9,000
  characters in the PRC's order, numbered here at each stroke's start. Arphic
  Public License.

What is not here: a site per character (twpen.com, which Bru pointed at, is
all rights reserved and draws Taiwan's order), Korean, and the alphabets. See
`docs/execution/stroke-order.md`.
"""

from __future__ import annotations

import json
import zipfile
from dataclasses import dataclass
from functools import cache
from pathlib import Path

from decker import script
from decker.console import VERBOSE, log
from decker.wiktionary import cache_dir, download


@dataclass(frozen=True)
class Source:
    #: The prefix of every media file drawn from it, which is also how a card
    #: being written says whose drawing it carries: see :func:`credit`.
    name: str
    url: str
    #: The one-line credit each card carries, as the licence asks.
    credit: str
    #: Which scripts it draws. A Latin `A` or a digit in a Japanese text is in
    #: KanjiVG too, but it is not a character the deck is teaching to write.
    scripts: frozenset[str]


KANJIVG = Source(
    name="kanjivg",
    #: Pinned rather than asked for: a release is the data the docs measured,
    #: and the API call to find the latest would be one more thing to wait on.
    url=(
        "https://github.com/KanjiVG/kanjivg/releases/download/r20260714/"
        "kanjivg-20260714-main.zip"
    ),
    credit=(
        'Stroke order: <a href="https://kanjivg.tagaini.net">KanjiVG</a>, '
        '<a href="https://creativecommons.org/licenses/by-sa/3.0/">CC BY-SA 3.0</a>'
    ),
    scripts=frozenset({"HIRAGANA", "KATAKANA", script.HAN}),
)

MAKEMEAHANZI = Source(
    name="makemeahanzi",
    url="https://raw.githubusercontent.com/skishore/makemeahanzi/master/graphics.txt",
    credit=(
        'Stroke order: <a href="https://github.com/skishore/makemeahanzi">'
        "Make Me a Hanzi</a>, Arphic Public License"
    ),
    scripts=frozenset({script.HAN}),
)

#: Which order a target language writes in. Cantonese is left out: Hong Kong's
#: order is a third standard, and drawing the PRC's for it would be a card that
#: looks right and teaches a hand it does not use.
SOURCES = {
    "ja": KANJIVG,
    "zh": MAKEMEAHANZI,
    "zh-hans": MAKEMEAHANZI,
    "zh-hant": MAKEMEAHANZI,
}

_BY_NAME = {source.name: source for source in (KANJIVG, MAKEMEAHANZI)}


def drawn(character: str, lang: str) -> str:
    """The cached SVG of ``character``'s strokes as ``lang`` writes them.

    Empty when the term is not one character, the language has no source, or
    the source does not have it. Only a term that is a single character has a
    drawing: a word's order is its characters' orders, each on its own card.
    """
    source = SOURCES.get(lang)
    if source is None or len(character) != 1:
        return ""
    if script.script_of(character) not in source.scripts:
        return ""
    path = _media(source, character)
    if path.exists():
        return str(path)
    svg = _from_kanjivg(character) if source is KANJIVG else _from_hanzi(character)
    if not svg:
        return ""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(svg, encoding="utf-8")
    return str(path)


def credit(path: str) -> str:
    """The credit line the drawing at ``path`` has to carry."""
    source = _BY_NAME.get(Path(path).name.split("-")[2]) if path else None
    return source.credit if source else ""


def _media(source: Source, character: str) -> Path:
    #: Anki keeps every deck's media in one folder by bare name, so the name
    #: says it is decker's and whose drawing it is, not just which code point.
    return (
        cache_dir() / "strokes" / f"decker-strokes-{source.name}-{ord(character):05x}.svg"
    )


def _archive(source: Source) -> Path:
    path = cache_dir() / "strokes" / source.url.rsplit("/", 1)[-1]
    if not path.exists():
        download(source.url, path, phase="strokes")
        log(
            f"[decker] {path.stat().st_size // (1 << 20)} MB of stroke orders "
            f"cached at {path}",
            level=VERBOSE,
            kind="detail",
        )
    return path


@cache
def _kanjivg_names() -> tuple[zipfile.ZipFile, frozenset[str]]:
    archive = zipfile.ZipFile(_archive(KANJIVG))
    return archive, frozenset(archive.namelist())


def _from_kanjivg(character: str) -> str:
    """KanjiVG's own file for the character, licence comment and numbers in it.

    The base file only: `-Kaisho` and the other variants are other hands.
    """
    archive, names = _kanjivg_names()
    name = f"kanji/{ord(character):05x}.svg"
    return archive.read(name).decode("utf-8") if name in names else ""


@cache
def _hanzi() -> dict[str, str]:
    """Make Me a Hanzi's lines, by character; parsed only when drawn."""
    lines: dict[str, str] = {}
    with _archive(MAKEMEAHANZI).open(encoding="utf-8") as data:
        for line in data:
            #: `{"character":"所",...`: the character is the first field, so
            #: indexing 9,000 lines does not mean parsing 30 MB of JSON.
            lines[line[14]] = line
    return lines


def _from_hanzi(character: str) -> str:
    """The character drawn from its outlines, numbered at each stroke's start.

    Make Me a Hanzi's coordinates are a 1024 box with y pointing up and the
    baseline at 900, which the outer transform undoes; the numbers are placed
    in page coordinates so that they are not drawn upside down.
    """
    line = _hanzi().get(character)
    if line is None:
        return ""
    data = json.loads(line)
    strokes = "".join(f'<path d="{d}"/>' for d in data["strokes"])
    numbers = "".join(
        f'<text x="{x - 70}" y="{900 - y - 10}">{number}</text>'
        for number, ((x, y), *_) in enumerate(data["medians"], start=1)
    )
    return (
        "<!-- Make Me a Hanzi (https://github.com/skishore/makemeahanzi), "
        "Arphic Public License; drawn by decker. -->\n"
        '<svg xmlns="http://www.w3.org/2000/svg" width="109" height="109" '
        'viewBox="0 0 1024 1024">'
        f'<g transform="scale(1,-1) translate(0,-900)" fill="#000000">{strokes}</g>'
        #: Red rather than KanjiVG's grey, since here the numbers sit on
        #: filled strokes rather than beside thin lines.
        '<g font-size="80" font-weight="bold" font-family="sans-serif" '
        'fill="#d03030">'
        f"{numbers}</g></svg>\n"
    )

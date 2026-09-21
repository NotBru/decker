"""A manga volume as a source: what a mokuro archive is once the page is gone.

The design leaves source format normalization out of v1 -- "the input is
already text" -- and :mod:`decker.subtitles` already had to bend that once. A
manga is the same bend one step further: the text of a volume exists, but it
exists as a few hundred speech bubbles scattered over seventy images, and
somebody else's OCR is what put it into words. `mokuro` is that OCR, and a
`.mbz` archive -- the zip it writes, or the folder that zip unpacks to -- is a
volume's pages beside a `_ocr/<page>.json` for each of them:

* **`blocks`** are the bubbles the text detector found, one per thing somebody
  said, in reading order: right to left, top to bottom, banded by panel.
* **`lines`** are the columns that bubble's text is set in. Vertical Japanese
  wraps right to left, so a five-line bubble is one utterance cut into five
  pieces by how wide the bubble was -- the same cut a cue file makes, for the
  same reason, and undone here the same way.
* **`box`**, **`lines_coords`**, **`font_size`**, **`vertical`** are where on
  the page it all was, which is the page's business and not the deck's.

So a block is a sentence and its lines are folded back into one, pages are read
in the order the volume's `mokuro-metadata.json` lists them, and what comes out
is prose that the rest of the pipeline cannot tell from a book. Three things a
manga has that a book does not:

* **Bubbles that are not words.** `⋯`, `‼︎！`, `？？` -- a beat, a shock, a
  double take, drawn as punctuation with nothing said. Eighteen of one volume's
  461 blocks are nothing else, and a term extractor handed one has nothing to
  find. A block with no character in any script is dropped: see
  :func:`_speech`.
* **Sound effects the OCR read as words.** `午短短短知短う`, off a hand-drawn
  スパァン. Nothing here can tell those from speech -- they are kanji in a box
  like any other -- so they pass, and `--unknowns` is what meets them further
  down.
* **Sentences of nine characters.** The median block of that volume is two
  lines and nine characters long, which is the whole context a disambiguation
  prompt gets for a word in it. That is not a defect to fix; it is what a
  comic is, and the same thinness dialogue subtitles have.
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

from decker.script import script_of

#: What a mokuro archive is called: mokuro writes `<volume>.mbz.zip`, and
#: unpacking it gives `<volume>.mbz`, a folder of the same shape. Both are
#: read, and neither is *recognized* by its name -- :func:`looks_like` opens
#: it. This is here for the deck's filename, which has to lose both halves of
#: a double extension: `Path("0001.mbz.zip").stem` is `0001.mbz`.
SUFFIXES = (".mbz", ".mbz.zip")

#: The file mokuro writes beside the pages, naming the series, the volume and
#: the page order. Everything else in an archive can be found without it; the
#: order cannot, since `0010.png` sorts before `0002.png` in some archives and
#: a volume read out of order is a deck taught out of order.
METADATA = "mokuro-metadata.json"

#: The folder the per-page OCR is written to, under the archive's root.
OCR = "_ocr/"


def looks_like(source: str) -> bool:
    """Whether this source is a mokuro archive, by what is in it.

    By content rather than by name, unlike the cue files: a folder called
    anything at all is a mokuro archive if it holds a `_ocr/` of JSON, and a
    `.mbz.zip` holding no such thing is not one however it is named.
    :data:`SUFFIXES` is what the *name* is good for -- naming the deck -- and
    is not consulted here. Standard input cannot be sniffed, the archive being
    a zip and decker reading stdin as text, so `-` is never this.
    """
    if source == "-":
        return False
    path = Path(source)
    if not path.exists():
        return False
    if path.is_dir():
        return (path / OCR).is_dir() or (path / METADATA).is_file()
    if not zipfile.is_zipfile(path):
        return False
    with zipfile.ZipFile(path) as archive:
        return any(_root(name) is not None for name in archive.namelist())


def text_of(source: str) -> str:
    """The volume's speech, page by page and bubble by bubble, as one text.

    Each bubble is a paragraph. A blank line is how a sentence boundary is put
    to Stanza, which splits on one and not on a bare newline, and it is needed
    here for the reason it is needed for machine captions: a manga punctuates
    when it feels like it, and `もう帰ろう` in one bubble and `まだだ` in the
    next are two sentences with nothing between them to say so.
    """
    return "\n\n".join(_speech(source))


def title_of(source: str) -> str:
    """What the volume calls itself -- `Gokurakugai 0001` -- or `""`.

    The archive's own name is a number often enough (`0001.mbz.zip`) that a
    deck named after the file would be called `0001` in Anki and sit there
    unidentifiable beside next month's. The metadata knows the series, so the
    deck's *title* comes from here when there is one; its *filename* does not,
    that being the user's own word for where the deck should land.
    """
    metadata = _metadata(_members(Path(source)))
    series = (metadata.get("series") or "").strip()
    volume = (metadata.get("volume") or metadata.get("title") or "").strip()
    return " ".join(part for part in (series, volume) if part)


def _speech(source: str) -> list[str]:
    """Every bubble of the volume that says something, in reading order."""
    members = _members(Path(source))
    said: list[str] = []
    for name in _pages(members):
        page = json.loads(members[name].decode("utf-8"))
        for block in page.get("blocks", ()):
            lines = [line.strip() for line in block.get("lines", ()) if line.strip()]
            if not lines:
                continue
            text = _folded(lines)
            #: A bubble of pure punctuation is a drawn beat, not a sentence.
            #: `script_of` answers `""` for everything that is not a writing
            #: system -- the ellipses, the interrobangs, the digits -- so a
            #: block with no scripted character in it has no word in it.
            if any(script_of(character) for character in text):
                said.append(text)
    return said


def _folded(lines: list[str]) -> str:
    """One bubble's columns, joined back into the sentence they were cut from.

    A space goes in only where both sides of the cut are written in a script
    that spaces its words. Japanese is not one, and `タオさん` + `いんなら`
    joined with a space is two tokens where the page had one; a bubble of
    English or Russian -- a sign, a title page, a translator's note -- is, and
    loses its word boundary if the seam is closed. The scripts decide, rather
    than `--target-lang`, because a volume can hold both and often does.
    """
    text = lines[0]
    for line in lines[1:]:
        text += (" " if _spaced(text[-1]) and _spaced(line[0]) else "") + line
    return text


#: The scripts that write a word without spaces between the next one. A seam
#: inside a bubble closes up when it falls between two of these, and opens
#: into a space otherwise. Han, the kana and Thai are the ones decker has been
#: run over; the rest of the unspaced scripts belong here as they turn up.
_UNSPACED = frozenset({"CJK", "HIRAGANA", "KATAKANA", "THAI", "LAO", "KHMER"})


def _spaced(character: str) -> bool:
    """Whether this character belongs to a script that separates its words."""
    script = script_of(character)
    return bool(script) and script not in _UNSPACED


def _members(path: Path) -> dict[str, bytes]:
    """The archive's JSON, by path within it -- and only its JSON.

    A volume is a few hundred megabytes of PNG around a few kilobytes of text,
    and none of the pictures is wanted here. A folder and a zip answer the
    same way so that the rest of the module never learns which it was given.
    """
    if path.is_dir():
        return {
            found.relative_to(path).as_posix(): found.read_bytes()
            for found in sorted(path.rglob("*.json"))
            if found.is_file()
        }
    with zipfile.ZipFile(path) as archive:
        return {
            name: archive.read(name)
            for name in archive.namelist()
            if name.lower().endswith(".json")
        }


def _pages(members: dict[str, bytes]) -> list[str]:
    """The OCR files of a volume, in the order the volume is read.

    `mokuro-metadata.json` lists them and is believed. Without it the names
    are sorted, which is right for the zero-padded numbering mokuro writes and
    is the best that can be done for anything else.
    """
    metadata = _metadata(members)
    root = _prefix(members)
    listed = [
        root + page[1]
        for page in metadata.get("pages", ())
        if isinstance(page, list) and len(page) > 1
    ]
    found = [name for name in listed if name in members]
    if found:
        return found
    return sorted(name for name in members if _root(name) is not None)


def _metadata(members: dict[str, bytes]) -> dict:
    """What the archive says about itself, or `{}` when it says nothing."""
    name = _prefix(members) + METADATA
    if name not in members:
        return {}
    try:
        found = json.loads(members[name].decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return {}
    return found if isinstance(found, dict) else {}


def _prefix(members: dict[str, bytes]) -> str:
    """The path the archive's root sits at, which is usually nothing at all.

    mokuro zips a volume from inside it, so `_ocr/0001.json` is at the top.
    Anything repacked by hand is as likely to carry the folder along, and then
    every name is `0001.mbz/_ocr/0001.json`; the first OCR file says which.
    """
    for name in sorted(members):
        root = _root(name)
        if root is not None:
            return root
    return ""


def _root(name: str) -> str | None:
    """Whatever precedes `_ocr/` in this member's name, if it is OCR at all."""
    if not name.lower().endswith(".json"):
        return None
    head, marker, _ = name.partition(OCR)
    return head if marker else None

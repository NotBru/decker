"""Kana runs that are only the reading of another word.

A language written without spaces has its compounds found as runs of tokens
whose spelling is a title (see `wiktionary.build_index`). Japanese Wiktionary
also titles a page by the *kana* of a word normally written in kanji, so a run
of kana can spell a title by coincidence: `そう` + `だ`, *so it is*, spells
`そうだ`, whose page holds only 操舵, *steering*. Parsing the title does not
tell them apart -- it cuts into the same two tokens the text did -- and sense
disambiguation cannot either, since the page has no other sense to choose.

What does tell them apart is where the kanji spelling's words fall. A kana run
that really is the word the page names is that word written another way, cut
in the same places: `かもしれない` is `かも知れない`, `みなさん` is `皆さん`,
`にげて` is `逃げて`. A run that only shares its sound crosses the spelling's
words: 操舵 is one word, and `そうだ` is two. So a kana title is kept when one
of its senses is the kana's own, or names a spelling whose reading is the run
and whose words end wherever the run's do; and dropped when every sense names
a spelling, and none of them is cut that way. The measurements are in
`docs/execution/term-extraction.md`.
"""

from __future__ import annotations

import re

from decker.nlp import boundaries
from decker.pages import spellings_named

_KANA = re.compile(r"^[ぁ-ゟ゠-ヿ]+$")
_KANJI = re.compile(r"[㐀-䶿一-鿿々]")


def kana_only(title: str) -> bool:
    """Whether ``title`` is written in kana alone."""
    return bool(_KANA.match(title))


def read_as_another(title: str, *, edition: str, lang: str) -> str | None:
    """The spelling ``title`` is only the reading of, or ``None`` if it is a word.

    Asked of kana titles alone: a title with a kanji in it is written the way
    the text wrote it, and is the word. A page that cannot be read says
    nothing either way, and the title is kept.
    """
    groups = spellings_named(title, edition=edition, lang=lang)
    if not groups:
        return None
    ends = set(boundaries(title))
    first: str | None = None
    for group in groups:
        named = [spelling for spelling in group if _KANJI.search(spelling)]
        if not named:
            return None
        for spelling in named:
            read = boundaries(spelling, read=True)
            if read and read[-1] == len(title) and ends <= set(read):
                return None
        first = first or named[0]
    return first

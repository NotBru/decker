"""Which of a card's characters the reader cannot yet read.

The design's *closed-form writing schemes* asks decker to notice when the
target language's writing system differs from the mother tongue's and teach
it, "even if it's just pronunciation". Read literally -- and it is what
`--teach-script` implements -- that is a property of a card rather than of a
language: every symbol a card puts in front of the reader that is not one of
their own must have been taught by an earlier card. A Spanish deck for a
speaker of English is mostly letters they already have, and then `ñ`, `¿`, and
the dozen IPA symbols the readings are written in; a Russian one is an
alphabet; a Chinese one is every character it shows.

This module answers only the narrow question -- given a mother tongue, which
characters of this text are foreign -- and :mod:`decker.glosses` turns the
answer into glosses. The rule it applies is the *repertoire*, not the Unicode
script, and that is the whole reason it exists: `ʃ` is a Latin letter as far
as Unicode is concerned (LATIN SMALL LETTER ESH) and no reader of English has
ever met it, so a script comparison would have let every IPA reading through
untaught -- and IPA is on nearly every card decker builds.
"""

from __future__ import annotations

import string
import unicodedata

#: What every writing system decker has been pointed at shares: the ASCII
#: digits, punctuation and space, the typographic spellings of the same marks,
#: the printer's marks a page of any language uses, and the digits again in
#: the two sizes a footnote and a formula write them in. Not "Unicode's Common
#: script", which would take in `¿`, `«` and `。` -- punctuation that is exactly
#: what a reader of English has to be taught.
#:
#: The marks past the dashes and quotes are here because a run turned them up:
#: Wiktionary's own bullet came off the definition of `мальчик` and a subscript
#: two off the etymology of `на`, and `Symbol: • BULLET` is not a card anybody
#: should be shown. Modifier letters are deliberately *not* here: `ʰ` and `ʲ`
#: are how IPA writes aspiration and palatalization, and teaching those is what
#: this stage is for.
SHARED = (
    frozenset(string.digits + string.punctuation + string.whitespace)
    | frozenset("–—‘’“”…")
    | frozenset("•§©®™°±×÷′″†‡")
    | frozenset("⁰¹²³⁴⁵⁶⁷⁸⁹")
    | frozenset("₀₁₂₃₄₅₆₇₈₉")
)

#: The letters a mother tongue writes with, by language code. One entry,
#: because v1 assumes English as the mother language and English is the only
#: repertoire a run here has been measured against; the rule for adding one is
#: `_SECTIONS`' rule in :mod:`decker.languages`, and the cost of a missing
#: entry is stated rather than guessed at -- :func:`familiar` answers ``None``
#: for a language that is not here, and `--teach-script` says so and stands
#: down rather than teaching a reader of Portuguese the letter `a`.
#:
#: Upper case is derived, not written: a repertoire is a set of letters and
#: every one of them is displayed in both cases.
_ALPHABETS = {"en": string.ascii_lowercase}

#: What a combining mark is shown on, so a card teaching one is not a card
#: showing nothing. U+25CC is the dotted circle typography already uses for
#: this, and it is what Wiktionary titles such entries with.
CARRIER = "◌"

#: Characters that take up no room on a card: controls, the format characters
#: (soft hyphen, the bidi marks, the zero-width joiners a script needs but a
#: reader never sees) and every kind of space. Nothing here is a symbol to be
#: taught, and a card fronted by an invisible one would be unanswerable.
_INVISIBLE = {"Cc", "Cf", "Cs", "Co", "Cn", "Zs", "Zl", "Zp"}

_MARKS = {"Mn", "Mc", "Me"}


def familiar(code: str) -> frozenset[str] | None:
    """Every character a reader of ``code`` already reads, or ``None``.

    ``None`` means decker does not know that language's repertoire, which is
    not the same as it having none: the caller has to decide what to do about
    it, and `--teach-script` turns itself off and says which language it was.
    """
    letters = _ALPHABETS.get(code.strip().casefold())
    if letters is None:
        return None
    return SHARED | frozenset(letters) | frozenset(letters.upper())


def foreign(text: str, known: frozenset[str]) -> list[str]:
    """The characters of ``text`` a reader of ``known`` cannot read.

    In the order they first appear, deduplicated, and with the invisible ones
    dropped. Case is *not* folded: `Д` and `д` are two shapes, and a learner
    who has been taught one has not been taught the other.
    """
    found: list[str] = []
    seen: set[str] = set()
    for character in text:
        if character in known or character in seen:
            continue
        if unicodedata.category(character) in _INVISIBLE:
            continue
        seen.add(character)
        found.append(character)
    return found


def displayed(character: str) -> str:
    """How the card shows this character on its own."""
    if unicodedata.category(character) in _MARKS:
        return CARRIER + character
    return character


def unicode_name(character: str) -> str:
    """What the Unicode character database calls it, or its code point.

    The last thing a symbol card can say when Wiktionary has no entry for the
    character. It is a poor definition -- INVERTED QUESTION MARK tells a
    learner the name of the shape and nothing about when it is used -- and it
    is true, which is the bar a card has to clear.
    """
    return unicodedata.name(character, f"U+{ord(character):04X}")

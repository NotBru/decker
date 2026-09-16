"""Which of a term's characters are written in a script the reader lacks.

The design's *closed-form writing schemes* asks decker to notice when the
target language's writing system differs from the mother tongue's and teach
it. `--teach-script` does that per character of a term rather than once per
language, because a language is not always one script: a Japanese sentence is
kanji, hiragana and katakana at once, and which of them a given word is written
in is a property of the word.

The comparison is between *scripts*, not between alphabets, and that is Bru's
call of 2026-09-16: **the Latin alphabet acts as one.** A reader of English
meeting `ñ`, `ç` or `é` is reading letters they can already read, with a mark
on them, and a card teaching `ç` to such a reader buys nothing. A reader of
English meeting `あ` cannot read it at all, and that card is the whole point --
"if you're learning Japanese, learning the kanas is gonna be part of it".

This module answers only the narrow question, given a mother tongue: which
characters of this term are in another script. :mod:`decker.glosses` turns the
answer into glosses.
"""

from __future__ import annotations

import unicodedata

#: The scripts decker can name, spelled as the Unicode character database
#: spells them inside a character's name -- `CYRILLIC SMALL LETTER ZHE`,
#: `HIRAGANA LETTER A`, `CJK UNIFIED IDEOGRAPH-98DF`. A character's script is
#: the first of these its name mentions, which is what makes the table cheap:
#: Unicode has already done the work, and there is nothing here to keep up to
#: date beyond adding a name.
#:
#: A character whose name mentions none of them has no script as far as this
#: stage is concerned -- the digits, the punctuation, the currency signs, the
#: IPA modifiers -- and is never taught. A writing system is what the flag is
#: about; `¿` is not one, and neither is `%`.
SCRIPTS = frozenset(
    {
        "LATIN",
        "GREEK",
        "COPTIC",
        "CYRILLIC",
        "ARMENIAN",
        "HEBREW",
        "ARABIC",
        "SYRIAC",
        "THAANA",
        "NKO",
        "SAMARITAN",
        "DEVANAGARI",
        "BENGALI",
        "GURMUKHI",
        "GUJARATI",
        "ORIYA",
        "TAMIL",
        "TELUGU",
        "KANNADA",
        "MALAYALAM",
        "SINHALA",
        "THAI",
        "LAO",
        "TIBETAN",
        "MYANMAR",
        "GEORGIAN",
        "ETHIOPIC",
        "CHEROKEE",
        "CANADIAN",
        "OGHAM",
        "RUNIC",
        "KHMER",
        "MONGOLIAN",
        "HIRAGANA",
        "KATAKANA",
        "BOPOMOFO",
        "HANGUL",
        "CJK",
        "KANGXI",
        "YI",
        "VAI",
        "GOTHIC",
        "DESERET",
        "OSAGE",
        "ADLAM",
        "TIFINAGH",
        "JAVANESE",
        "BALINESE",
        "CHAM",
        "TAGALOG",
    }
)

#: The script or scripts a reader of this language already reads, by language
#: code. One entry, because v1 assumes English as the mother language and it is
#: the only one anything here has been run for; :func:`scripts_of` answers
#: ``None`` for anything else and `--teach-script` then says so and stands
#: down. The rule for adding one is `_SECTIONS`' rule in
#: :mod:`decker.languages`: an entry goes in when a run has been seen to need
#: it, and a Japanese reader learning Spanish is the run that would add `ja`.
_READS = {"en": ("LATIN",)}

#: What a combining mark is shown on, so a card teaching one is not a card
#: showing nothing. U+25CC is the dotted circle typography already uses for
#: this, and it is what Wiktionary titles such entries with.
CARRIER = "◌"

#: Characters that take up no room on a card: controls, the format characters
#: (soft hyphen, the bidi marks, the zero-width joiners a script needs but a
#: reader never sees) and every kind of space. A card fronted by one would be
#: unanswerable.
_INVISIBLE = {"Cc", "Cf", "Cs", "Co", "Cn", "Zs", "Zl", "Zp"}

_MARKS = {"Mn", "Mc", "Me"}


#: The Han script, as Unicode names it inside a character: `CJK UNIFIED
#: IDEOGRAPH-98DF`. Named here because :mod:`decker.glosses` has one rule that
#: applies to it and to no other script -- a Han character is a morpheme, so a
#: word entry may answer for it.
HAN = "CJK"


def scripts_of(code: str) -> tuple[str, ...] | None:
    """The scripts a reader of ``code`` already reads, or ``None``.

    ``None`` means decker does not know, which is not the same as the language
    having none: the caller decides what to do about it, and `--teach-script`
    turns itself off and says which language it was.
    """
    return _READS.get(code.strip().casefold())


def script_of(character: str, after: str = "") -> str:
    """The script ``character`` is written in, or ``""`` if it is in none.

    ``after`` is the character before it in the text, and answers for the
    combining marks: `COMBINING ACUTE ACCENT` names no script of its own, and
    the acute on a Latin `e` belongs to the Latin word it is part of. A mark
    that opens a string has nothing to belong to and is left scriptless.
    """
    if unicodedata.category(character) in _MARKS:
        own = _named(character)
        return own or (script_of(after) if after else "")
    return _named(character)


def foreign(term: str, reads: tuple[str, ...]) -> list[str]:
    """The characters of ``term`` written in a script ``reads`` does not cover.

    In the order they first appear, deduplicated. Case is *not* folded: `Д`
    and `д` are two shapes, and a learner who has been taught one has not been
    taught the other.
    """
    found: list[str] = []
    seen: set[str] = set()
    previous = ""
    for character in term:
        if character in seen or unicodedata.category(character) in _INVISIBLE:
            previous = character
            continue
        script = script_of(character, previous)
        previous = character
        if not script or script in reads:
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
    character. It is a poor definition -- `HIRAGANA LETTER SMALL A` tells a
    learner the name of the shape and nothing about its sound -- and it is
    true, which is the bar a card has to clear.
    """
    return unicodedata.name(character, f"U+{ord(character):04X}")


def _named(character: str) -> str:
    """The first script :data:`SCRIPTS` knows that this character's name names.

    The name is read word by word, hyphens split as spaces, so
    `KATAKANA-HIRAGANA PROLONGED SOUND MARK` is katakana and
    `FULLWIDTH LATIN CAPITAL LETTER A` is Latin rather than a script called
    fullwidth.
    """
    name = unicodedata.name(character, "")
    for word in name.replace("-", " ").split():
        if word in SCRIPTS:
            return word
    return ""

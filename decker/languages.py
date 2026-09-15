"""Language codes, and the one place a language has to be a word.

Every language decker is told about arrives as a code -- ``es``, ``pt``, ``en``
-- because that is the shape its consumers already share: Stanza keys its
models by code, and Wiktionary keys its editions by one too. A flag that took a
word instead would make the caller remember which of them wants which, so the
codes stop at the edge and everything below deals with them.

Two consumers want a word. The translation prompt is written for a model and
has to read ``a speaker of Portuguese``; and a Wiktionary page names its
language sections in English, so ``Spanish`` is what finds the section a gloss
is read from. Turning the code into that word is this module's whole job. The
table is Stanza's own -- four hundred codes it already ships, and decker
already depends on it -- so there is no map here to fall out of date and
nothing to fetch.
"""

from __future__ import annotations

#: Stanza's table, imported on first use: it lives under ``stanza.models``,
#: and importing that pulls torch in behind it. Every entry decker asks about
#: is a plain lowercase code.
_NAMES: dict[str, str] | None = None


def name_of(code: str) -> str:
    """The English name of ``code``, as a prompt would say it.

    Unknown codes come back as themselves. Callers that must not put a code
    in front of a model ask :func:`known` first -- the CLI does, so a
    mistyped flag is a message and not a card written for a speaker of ``pt-``.
    """
    return _names().get(_key(code), code)


def known(code: str) -> bool:
    """Whether ``code`` is a language code decker can name."""
    return _key(code) in _names()


def _key(code: str) -> str:
    return code.strip().casefold()


def _names() -> dict[str, str]:
    global _NAMES
    if _NAMES is None:
        from stanza.models.common.constant import lcode2lang

        #: Stanza writes the multi-word ones with underscores --
        #: ``Simplified_Chinese`` -- which is a table's spelling, not a
        #: sentence's.
        _NAMES = {
            code: name.replace("_", " ") for code, name in lcode2lang.items() if name
        }
    return _NAMES


#: Where Wiktionary's section heading and Stanza's name for a code part ways.
#: Stanza names the written variety where Wiktionary heads the language:
#: ``zh-hans`` is Stanza's *Simplified Chinese*, and the page 狗 heads one
#: *Chinese* section covering both scripts, so an unpatched run asks for a
#: heading no page carries and every Chinese lookup comes back empty --
#: measured, and the first finding of `docs/execution/language-survey.md`.
#: ``nb`` is the same mistake in a language nobody had run yet: Stanza says
#: *Norwegian*, and `hund` and `bok` both head *Norwegian Bokmål*.
#:
#: A table decker maintains, which the module docstring above says there is
#: none of -- and it stays this short for that reason. An entry is added when
#: a run has been seen to find nothing because of it, never on suspicion.
_SECTIONS = {
    "zh": "Chinese",
    "zh-hans": "Chinese",
    "zh-hant": "Chinese",
    #: The lects Stanza names separately and the English Wiktionary keeps
    #: under the one Chinese heading, with the variety marked inside the
    #: entry. Found by the audit in `local-wiktionary.md`: 狗 and 水 head
    #: `Chinese` and nothing else, so a run told `yue` reads an empty page
    #: exactly as `zh-hans` used to.
    "yue": "Chinese",
    "wuu": "Chinese",
    "lzh": "Chinese",
    "nb": "Norwegian Bokmål",
    "no": "Norwegian Bokmål",
}


def section_of(code: str) -> str:
    """The Wiktionary section heading a gloss for ``code`` is read from.

    Only the heading. What a prompt should call the language is a different
    question with a different answer -- a text in ``zh-hans`` really is in
    Simplified Chinese, and a model told so knows something true about it --
    so :func:`name_of` is what the prompts keep asking.
    """
    return _SECTIONS.get(_key(code)) or name_of(code)


#: How a language's Wiktionary spells a bound morpheme, where the parser hands
#: decker one. The second table of the same kind as :data:`_SECTIONS`, and kept
#: for the same reason: it is a fact about how the dictionary is written, not
#: about the language. Hebrew's tokenizer splits the clitic prefixes off, as it
#: should -- `לכל` is `ל` + `כל` -- and the plain letter is a page *about the
#: letter*: `ל` offers Lamed, the twelfth letter of the alphabet, and the
#: preposition is at `ל־`, with a maqaf. The survey taught five of the
#: commonest words in the language as names of letters because of it.
#:
#: One entry, because one language has been measured. A hyphen is the
#: Latin-script spelling of the same idea and would be wrong here: Spanish
#: `del` splits into two *free* words, and pooling the prefix `de-` into the
#: preposition `de` would offer the model a morpheme the sentence never used.
_JOINERS = {"he": "\u05be"}


def joiner_of(code: str) -> str:
    """The character this language's Wiktionary hangs a bound form on."""
    return _JOINERS.get(_key(code), "")


#: Which lect's pronunciation a code is being taught, where the entry gives one
#: per lect. The English Wiktionary writes a Chinese entry as a single section
#: with a pronunciation block per variety -- 狗 carries 59 readings over nine of
#: them, four Mandarin and twenty-seven Wu -- so a card built from the section
#: whole is a wall of transcriptions for varieties the learner is not studying.
#: The third table of the same kind as :data:`_SECTIONS` and :data:`_JOINERS`,
#: and the same rule: an entry goes in when a run has been seen to need it.
_LECTS = {
    "zh": "Mandarin",
    "zh-hans": "Mandarin",
    "zh-hant": "Mandarin",
    "yue": "Cantonese",
    "wuu": "Wu",
    "lzh": "Middle Chinese",
}


def lect_of(code: str) -> str:
    """The pronunciation block this code is taught from, if the entry has one."""
    return _LECTS.get(_key(code), "")

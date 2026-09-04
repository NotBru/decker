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

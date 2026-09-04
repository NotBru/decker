"""Decker: build Anki decks that teach the language of a source text.

v1 implements the whole pipeline -- sentencing, term extraction, definition
fetching, deck construction, shuffling and the Anki package; see
``docs/instructions/design.md``.
"""

from decker.pipeline import SentenceTerms, run
from decker.terms import Term

__all__ = ["SentenceTerms", "Term", "run"]

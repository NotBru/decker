"""Decker: build Anki decks that teach the language of a source text.

v1 implements the pipeline up to term extraction; see ``docs/instructions/design.md``.
"""

from decker.pipeline import SentenceTerms, run
from decker.terms import Term

__all__ = ["SentenceTerms", "Term", "run"]

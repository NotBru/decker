"""Deck construction: from glosses to cards.

Every gloss becomes the design's pair -- a recognition card, which shows the
term and asks what it means, and a production card, which shows the meaning
and asks for the term. The pair is the reason a gloss carries one sense and
not a page's worth: two cards per sense is a deck a learner can answer, two
cards per page is a card with a list on the back.

The prose on a card is Wiktionary's, so it is written in the edition's
language; when the mother language is not that one it goes through the
translator on its way onto the card, which is where the design puts it.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field

from decker.glosses import Gloss
from decker.ollama import DEFAULT_MODEL
from decker.translation import SOURCE_LANGUAGE, Translator

RECOGNITION = "recognition"
PRODUCTION = "production"


@dataclass(frozen=True)
class Side:
    """One face of a card: only the pieces the design puts on that face."""

    term: str | None = None
    definition: str | None = None
    examples: tuple[str, ...] = ()
    ipa: tuple[str, ...] = ()
    etymology: str | None = None
    #: Cached sound file, on the face that names the pronunciation.
    audio: str | None = None


@dataclass(frozen=True)
class Card:
    """One card: a challenge, its answer, and what must come before it."""

    #: Position in the list deck construction produced, and the card's
    #: identity: shuffling reorders the list without renumbering it.
    index: int
    #: ``RECOGNITION`` or ``PRODUCTION``.
    kind: str
    #: Index of the gloss this card teaches.
    gloss: int
    #: The Wiktionary page the gloss was read from, for the card's credit line.
    entry: str
    #: The language section it was read from, as Wiktionary names it.
    language: str
    challenge: Side
    answer: Side
    #: Indexes of the cards this one must appear after.
    depends_on: tuple[int, ...] = ()


@dataclass
class _Builder:
    """Accumulates cards, and remembers which card teaches which gloss."""

    cards: list[Card] = field(default_factory=list)
    #: Gloss index to the index of the recognition card that introduces it.
    introduced_by: dict[int, int] = field(default_factory=dict)

    def add(self, **fields) -> int:
        index = len(self.cards)
        self.cards.append(Card(index=index, **fields))
        return index


def build(
    glosses: list[Gloss],
    *,
    mother_language: str = SOURCE_LANGUAGE,
    model: str | None = None,
    host: str | None = None,
    translate: bool = True,
) -> list[Card]:
    """Turn definition fetching's output into the design's list of cards."""
    translator = Translator(
        mother_language=mother_language,
        model=model or DEFAULT_MODEL,
        host=host,
        enabled=translate,
    )
    builder = _Builder()
    for gloss in glosses:
        definition, examples, etymology = translator.gloss(
            definition=gloss.definition,
            examples=gloss.examples,
            etymology=gloss.etymology,
            target_language=gloss.language,
        )
        _pair(builder, gloss, definition, examples, etymology)
    print(f"[decker] {len(builder.cards)} cards", file=sys.stderr)
    return builder.cards


def _pair(
    builder: _Builder,
    gloss: Gloss,
    definition: str,
    examples: tuple[str, ...],
    etymology: str | None,
) -> None:
    """The recognition and production cards of one gloss, in that order."""
    recognition = builder.add(
        kind=RECOGNITION,
        gloss=gloss.index,
        entry=gloss.entry,
        language=gloss.language,
        challenge=Side(term=gloss.surface, examples=examples),
        #: The sound file rides with the reading: both answer the same
        #: question, and the run has already downloaded it.
        answer=Side(
            definition=definition,
            ipa=gloss.ipa,
            etymology=etymology,
            audio=gloss.audio,
        ),
        depends_on=_after(builder, gloss),
    )
    builder.introduced_by[gloss.index] = recognition
    builder.add(
        kind=PRODUCTION,
        gloss=gloss.index,
        entry=gloss.entry,
        language=gloss.language,
        challenge=Side(definition=definition),
        answer=Side(term=gloss.surface, ipa=gloss.ipa, etymology=etymology),
        #: Its own recognition card, and nothing else: whatever the gloss
        #: depends on is already behind that card, and the ordering the
        #: design asks for is transitive.
        depends_on=(recognition,),
    )


def _after(builder: _Builder, gloss: Gloss) -> tuple[int, ...]:
    """The cards a gloss's own card must follow.

    A gloss depends on the word its definition describes it in terms of --
    `patita` on `pata` -- and what that dependency asks is that the reader
    have met the word, which is what the recognition card is. Being able to
    produce `pata` on demand is a further thing, and not one `patita` needs.
    """
    return tuple(
        builder.introduced_by[index]
        for index in gloss.depends_on
        if index in builder.introduced_by
    )

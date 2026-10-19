"""Shuffling: the order the deck is learned in.

A deck built straight from the source teaches a text, not a language: the
cards of one sentence arrive together, and a word met on page one is never
seen again. Shuffling breaks that up, but only so far -- a card may not come
before what it depends on, and no card may travel far from where the source
put it, or the first week of a deck would be a sample of the whole text
instead of its opening.
"""

from __future__ import annotations

import random
from collections.abc import Iterable

from decker.cards import Card

#: The design's window: the number of cards a week of learning covers under
#: Anki's default settings. Shuffling happens inside one of these, never
#: across two, so a card stays in the week the source put it in.
WINDOW = 140


def shuffle(
    cards: Iterable[Card], *, seed: int | None = None, window: int = WINDOW
) -> list[Card]:
    """Reorder ``cards``, keeping every dependency ahead of what needs it.

    A window at a time: its cards shuffled, then put in dependency order by
    :func:`_dependency_order`, which sees the window and nothing else. A card
    whose dependency the source put in a later window cannot be ordered inside
    its own, so it is carried into the next one and shuffled there -- which
    the cards of one run's glosses never need, since a gloss depends on glosses
    built before it, but an edge `glosses._after` draws backwards could.
    """
    cards = list(cards)
    present = {card.index for card in cards}
    generator = random.Random(seed)
    taught: set[int] = set()
    order: list[Card] = []
    carried: list[Card] = []
    step = max(window, 1)
    for start in range(0, len(cards), step):
        block = carried + cards[start : start + step]
        within = {card.index for card in block}
        carried = [
            card for card in block
            if any(
                dependency in present and dependency not in taught
                and dependency not in within
                for dependency in card.depends_on
            )
        ]
        waiting = {card.index for card in carried}
        block = [card for card in block if card.index not in waiting]
        generator.shuffle(block)
        _dependency_order(block, generator)
        order += block
        taught.update(card.index for card in block)
    #: Only a cycle can leave a card carried past the last window, and
    #: dependencies point at cards already built, so this is unreachable --
    #: but dropping cards silently is not something to leave to that argument.
    return order + carried


def _dependency_order(cards: list[Card], generator: random.Random) -> None:
    """Put ``cards`` in dependency order, disturbing their order as little as
    the dependencies allow. In place.

    Read front to back. A card one of whose dependencies is still ahead of it
    swaps with a card drawn at random from the dependency's place to the end
    of the list, and the card that comes back into its place is read next. So
    a card that has to wait lands somewhere uniformly after what it waits for,
    and one card is moved for it rather than everything between.

    The sort this replaces, a stable topological sort, let a waiting card in
    the moment its dependency was placed whenever its own turn had already
    passed -- which is half the time -- and so put half of all production cards
    directly behind their recognition card, 2026-10-19.

    A dependency outside the list is taught already or cannot be waited for
    here; :func:`shuffle` keeps the second kind out. Swaps only ever send a
    card forward, past a dependency, so with no cycle among the dependencies
    the reading ends -- and a cycle, which dependencies pointing at cards
    already built cannot make, stops it after a bounded number of swaps
    rather than hanging the run.
    """
    at = {card.index: position for position, card in enumerate(cards)}
    position = 0
    swaps = 0
    while position < len(cards) and swaps <= len(cards) ** 2:
        card = cards[position]
        ahead = [
            at[dependency] for dependency in card.depends_on
            if dependency in at and dependency != card.index
            and at[dependency] > position
        ]
        if not ahead:
            position += 1
            continue
        other = generator.randint(max(ahead), len(cards) - 1)
        swaps += 1
        cards[position], cards[other] = cards[other], cards[position]
        at[cards[position].index] = position
        at[cards[other].index] = other

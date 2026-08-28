"""Shuffling: the order the deck is learned in.

A deck built straight from the source teaches a text, not a language: the
cards of one sentence arrive together, and a word met on page one is never
seen again. Shuffling breaks that up, but only so far -- a card may not come
before what it depends on, and no card may travel far from where the source
put it, or the first week of a deck would be a sample of the whole text
instead of its opening.
"""

from __future__ import annotations

import heapq
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
    """Reorder ``cards``, keeping every dependency ahead of what needs it."""
    cards = list(cards)
    return _topological(cards, _shuffled_keys(len(cards), seed=seed, window=window))


def _shuffled_keys(count: int, *, seed: int | None, window: int) -> list[int]:
    """A sort key per card: its own position, permuted within its window.

    The keys of a window are that window's own positions, so sorting by them
    can move a card around inside its week and nowhere else.
    """
    keys = list(range(count))
    generator = random.Random(seed)
    for start in range(0, count, max(window, 1)):
        block = keys[start : start + window]
        generator.shuffle(block)
        keys[start : start + window] = block
    return keys


def _topological(cards: list[Card], keys: list[int]) -> list[Card]:
    """Stable topological sort of ``cards``, keyed by the shuffled order.

    Kahn's algorithm taking, at every step, the ready card with the smallest
    key: a card waits exactly as long as its dependencies make it wait and no
    longer, which is what makes the sort stable in the shuffled order rather
    than merely correct.
    """
    at = {card.index: position for position, card in enumerate(cards)}
    waiting_on = {card.index: 0 for card in cards}
    unblocks: dict[int, list[int]] = {card.index: [] for card in cards}
    for card in cards:
        for dependency in card.depends_on:
            if dependency not in waiting_on or dependency == card.index:
                #: A dependency outside the deck cannot be waited for. It does
                #: not happen with cards built from one run's glosses, and a
                #: silent hang here would be worse than ignoring it.
                continue
            waiting_on[card.index] += 1
            unblocks[dependency].append(card.index)

    ready = [
        (keys[at[index]], index) for index, blocked in waiting_on.items() if not blocked
    ]
    heapq.heapify(ready)
    order = []
    while ready:
        _, index = heapq.heappop(ready)
        order.append(cards[at[index]])
        for dependent in unblocks[index]:
            waiting_on[dependent] -= 1
            if not waiting_on[dependent]:
                heapq.heappush(ready, (keys[at[dependent]], dependent))

    if len(order) != len(cards):
        #: Only a cycle can leave cards unplaced, and dependencies point at
        #: cards already built, so this is unreachable -- but dropping cards
        #: silently is not something to leave to that argument.
        placed = {card.index for card in order}
        order += [card for card in cards if card.index not in placed]
    return order

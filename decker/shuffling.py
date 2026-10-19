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
#: Anki's default settings, and the furthest a card may move from where the
#: source put it.
WINDOW = 140

#: How far past its latest dependency a card is put, drawn uniformly: far
#: enough that it is not that card's neighbour, near enough that a chain --
#: symbol, word, its production card -- does not run into the drift bound
#: at every step. Measured over Gokurakugai 0001, 2026-10-19; see
#: `docs/execution/deck-building.md`.
GAP = (10, 70)


def shuffle(
    cards: Iterable[Card], *, seed: int | None = None, window: int = WINDOW
) -> list[Card]:
    """Reorder ``cards``, keeping every dependency ahead of what needs it and
    every card within ``window`` places of where the source put it.

    Each card is given a key: its source position plus a random amount below
    ``window`` -- less for a card others wait on, see ``height`` below --
    raised to a random gap past its latest dependency's key, and sorted on. There are no weeks in it -- a fixed week made its first cards
    the ones with nothing to wait for and its last the ones that had waited,
    since a card cannot wait past the end of a week -- so every stretch of the
    deck has the mix the source has, 2026-10-19.

    **The bound is on the key, and so on the place.** A key never leaves
    ``[position, position + window]``: a card the gap would push past that is
    drawn instead from between its dependency's key and the bound, which is
    never empty when the dependency comes earlier in the source -- its own key
    is at most its own position plus ``window``. Every card whose source
    position is more than ``window`` before a card's key sorts ahead of it and
    every card whose position is past that key sorts behind it, so no card
    moves more than ``window`` places either way.

    Drawn, not pinned to the bound: cards pinned there would keep their source
    order among themselves, and a production card is next to its recognition
    card in the source.

    Ties sort by the card's index, which is what makes a seed reproduce a deck;
    a card never ties with its dependency, whose key is strictly lower.
    """
    cards = list(cards)
    generator = random.Random(seed)
    keys: dict[int, float] = {}
    ordered = _in_dependency_order(cards)
    #: How long a chain of cards waits below each one: a production card 0,
    #: its recognition card 1, a symbol that word is written with 2. A card
    #: draws its own key from the first ``1 / (height + 1)`` of its room, so
    #: what waits for it has the rest: drawn from the whole of it, a
    #: recognition card near its bound left its production card a sliver,
    #: and 5.5% of them landed adjacent; with the room shared, 0.3%.
    height = {card.index: 0 for card in cards}
    for _, card in reversed(ordered):
        for dependency in card.depends_on:
            if dependency in height and dependency != card.index:
                height[dependency] = max(height[dependency], height[card.index] + 1)
    for position, card in ordered:
        ceiling = position + window
        key = position + generator.random() * window / (height[card.index] + 1)
        after = [keys[dependency] for dependency in card.depends_on if dependency in keys]
        if after:
            floor = max(after)
            key = max(key, floor + generator.uniform(*GAP))
            if key > ceiling:
                #: In (floor, ceiling]: `random()` is below 1, so never the
                #: floor itself. Where the floor is past the ceiling -- a
                #: dependency the source put *after* this card -- ordering
                #: wins over the bound, as it always has: a card whose
                #: dependency the reader has not met teaches nothing.
                key = (
                    ceiling - generator.random() * (ceiling - floor)
                    if floor < ceiling
                    else floor + generator.uniform(*GAP)
                )
        keys[card.index] = key
    return sorted(cards, key=lambda card: (keys[card.index], card.index))


def _in_dependency_order(cards: list[Card]) -> list[tuple[int, Card]]:
    """``cards`` with their source positions, every card after the cards it
    depends on and otherwise in source order.

    That is source order itself whenever every dependency was built before
    the card that needs it, which is how one run's glosses come; the edge
    `glosses._after` draws backwards is the case it is for.
    """
    at = {card.index: position for position, card in enumerate(cards)}
    waiting_on = {card.index: 0 for card in cards}
    unblocks: dict[int, list[int]] = {card.index: [] for card in cards}
    for card in cards:
        for dependency in set(card.depends_on):
            if dependency in at and dependency != card.index:
                waiting_on[card.index] += 1
                unblocks[dependency].append(card.index)
    ready = [at[index] for index, blocked in waiting_on.items() if not blocked]
    heapq.heapify(ready)
    order = []
    while ready:
        position = heapq.heappop(ready)
        card = cards[position]
        order.append((position, card))
        for dependent in unblocks[card.index]:
            waiting_on[dependent] -= 1
            if not waiting_on[dependent]:
                heapq.heappush(ready, at[dependent])
    if len(order) != len(cards):
        #: Only a cycle can leave a card out, and dependencies point at cards
        #: already built, so this is unreachable -- but dropping cards
        #: silently is not something to leave to that argument.
        placed = {card.index for _, card in order}
        order += [(at[card.index], card) for card in cards if card.index not in placed]
    return order

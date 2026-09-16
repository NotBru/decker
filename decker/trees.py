"""UD dependency trees with deprels reified as nodes, and subtree matching.

A tree is made of token nodes whose children are the deprel-labelled edges
described in the v1 design: ``give --compound:prt--> up`` is a token node
``give`` with one child edge ``compound:prt`` leading to the token node ``up``.

Token nodes carry a *set* of labels rather than a single one. A Wiktionary
title contributes only the spelling it is written with, while a token of the
source text contributes every spelling it could be looked up under: its
surface form, its lemma, and -- for separable verbs -- the lemma glued to its
particle (``siehst ... aus`` also answers to ``aussehen``).
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

#: Deprel of a verb particle, which Wiktionary may write joined to its verb.
PARTICLE_DEPREL = "compound:prt"

#: Languages whose separable verbs are written as one word, so that a particle
#: hanging off a verb still belongs to the entry ``aussehen`` rather than to
#: ``sehen``. English keeps its particles apart -- ``gave ... up`` is the entry
#: ``give up``, never ``upgive`` -- so it is not in here.
JOINED_PARTICLE_LANGS = frozenset({"af", "de", "hu", "nl"})


def joins_particles(lang: str) -> bool:
    """Does ``lang`` write a verb and its particle as one word?"""
    return lang in JOINED_PARTICLE_LANGS


@dataclass(frozen=True)
class Edge:
    """A deprel node: the arrow's label, plus the token node it points at."""

    deprel: str
    child: "Node"


@dataclass(frozen=True)
class Node:
    """A token node."""

    labels: frozenset[str]
    children: tuple[Edge, ...] = ()
    #: Source-text tokens this node stands for (empty for title trees).
    tokens: frozenset[int] = frozenset()
    #: Extra tokens pulled in when the node is matched through a given label,
    #: e.g. the particle of a separable verb matched as ``aussehen``.
    label_tokens: tuple[tuple[str, frozenset[int]], ...] = ()

    def walk(self) -> Iterator["Node"]:
        yield self
        for edge in self.children:
            yield from edge.child.walk()


def sentence_tree(sentence: Any, *, join_particles: bool = False) -> list[Node]:
    """Build the token-node trees of a parsed Stanza sentence (usually one)."""
    words = list(sentence.words)
    children: dict[int, list[Any]] = {word.id: [] for word in words}
    roots: list[Any] = []
    for word in words:
        if word.head and word.head in children:
            children[word.head].append(word)
        else:
            roots.append(word)

    lowerable = positional_capital_ids(sentence)

    def build(word: Any) -> Node:
        edges = tuple(
            Edge(child.deprel, build(child)) for child in children[word.id]
        )
        labels = {word.text, word.lemma or word.text}
        if word.id in lowerable:
            labels |= {label.lower() for label in labels}
        label_tokens = []
        for child in children[word.id] if join_particles else ():
            if child.deprel != PARTICLE_DEPREL:
                continue
            particle = child.lemma or child.text
            for stem in (word.lemma or word.text, word.text):
                joined = f"{particle}{stem}".lower()
                labels.add(joined)
                label_tokens.append((joined, frozenset({child.id})))
        return Node(
            labels=frozenset(labels),
            children=edges,
            tokens=frozenset({word.id}),
            label_tokens=tuple(label_tokens),
        )

    return [build(root) for root in roots]


def positional_capital_ids(sentence: Any) -> set[int]:
    """Ids of the words whose capital may belong to the position, not to them.

    The sentence's opening, and the opening of every *line* inside it. The
    first is the old rule: nothing but punctuation before it, so the capital
    is the sentence start's and the word may also be looked up in lower case
    (``Lo`` -> ``lo``). A capital anywhere else is the word's own.

    The second is the same claim wherever the parser could not see a sentence
    end. Lyrics and captions are written a line at a time and punctuated
    barely or not at all, so Stanza reads five lines as one sentence, and
    every line but the first keeps a capital that is the line's and not the
    word's. Without this they are looked up capitalised only: `Упавший` never
    reaches `упавший`, and the occurrence falls back to the lemma's entry,
    `упасть`, which is a different word with a different card. Bru found the
    card in a deck built from lyrics, 2026-09-16; 818 of that deck's 6,521
    word cards were fronted with a form their back did not teach.

    Punctuation at a line's head is passed over as it is at the sentence's --
    a caption's leading dash does not make the speaker's first word the
    word's own capital.
    """
    words = list(sentence.words)
    text = getattr(sentence, "text", "") or ""
    tokens = getattr(sentence, "tokens", None) or []
    base = tokens[0].start_char if tokens else 0
    initial: set[int] = set()
    opening = True
    for position, word in enumerate(words):
        if opening:
            initial.add(word.id)
            opening = word.upos == "PUNCT"
        if _breaks_line(text, base, word, words[position + 1 :]):
            opening = True
    return initial


def _breaks_line(text: str, base: int, word: Any, rest: list[Any]) -> bool:
    """Whether a line ends between this word and the next one.

    Read off the sentence's own text rather than the tokens, because the
    break is exactly what the tokens do not carry. A parse that offers no
    offsets -- nothing decker runs does -- answers no, and the rule falls
    back to the sentence's opening alone.
    """
    following = next((one for one in rest), None)
    if following is None:
        return False
    ends = getattr(getattr(word, "parent", None) or word, "end_char", None)
    starts = getattr(getattr(following, "parent", None) or following, "start_char", None)
    if ends is None or starts is None:
        return False
    return "\n" in text[ends - base : starts - base]


def title_tree(sentence: Any) -> Node | None:
    """Build the pattern tree of a parsed Wiktionary title.

    Returns ``None`` for titles that do not parse into a single tree.
    """
    trees = sentence_tree(sentence)
    if len(trees) != 1:
        return None
    return _as_pattern(trees[0], {word.id: word.text for word in sentence.words})


def _as_pattern(node: Node, texts: dict[int, str]) -> Node:
    """Strip a tree down to the spellings the title is actually written with."""
    labels = frozenset(texts[token] for token in node.tokens)
    return Node(
        labels=labels,
        children=tuple(
            Edge(edge.deprel, _as_pattern(edge.child, texts)) for edge in node.children
        ),
    )


def match(pattern: Node, target: Node) -> frozenset[int] | None:
    """Match ``pattern`` at ``target``, returning the source tokens it covers.

    ``pattern`` matches when every one of its token nodes lines up with a
    target token node sharing a label, and every deprel edge of the pattern is
    a deprel edge of the target. The target may have any number of extra
    children, so ``give --compound:prt--> up`` matches ``gave himself up``.
    """
    shared = pattern.labels & target.labels
    if not shared:
        return None
    tokens = set(target.tokens)
    for label, extra in target.label_tokens:
        if label in shared:
            tokens |= extra
    below = _match_children(pattern.children, target.children)
    if below is None:
        return None
    return frozenset(tokens | below)


def _match_children(
    patterns: tuple[Edge, ...], targets: tuple[Edge, ...]
) -> set[int] | None:
    """Assign each pattern edge a distinct target edge, backtracking on failure."""
    if not patterns:
        return set()
    used: set[int] = set()
    covered: set[int] = set()

    def assign(index: int) -> bool:
        if index == len(patterns):
            return True
        pattern = patterns[index]
        for position, target in enumerate(targets):
            if position in used or target.deprel != pattern.deprel:
                continue
            tokens = match(pattern.child, target.child)
            if tokens is None:
                continue
            used.add(position)
            restore = set(covered)
            covered.update(tokens)
            if assign(index + 1):
                return True
            used.discard(position)
            covered.clear()
            covered.update(restore)
        return False

    return covered if assign(0) else None


def to_json(node: Node) -> dict[str, Any]:
    """Serialize a pattern tree (labels and structure only)."""
    return {
        "l": sorted(node.labels),
        "c": [[edge.deprel, to_json(edge.child)] for edge in node.children],
    }


def from_json(data: dict[str, Any]) -> Node:
    return Node(
        labels=frozenset(data["l"]),
        children=tuple(
            Edge(deprel, from_json(child)) for deprel, child in data["c"]
        ),
    )

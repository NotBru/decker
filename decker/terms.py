"""Term extraction: which Wiktionary entries a sentence is made of."""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from typing import Any

from decker import trees
from decker.wiktionary import TitleIndex


@dataclass(frozen=True)
class Term:
    """A term of a sentence, in the inflected form the sentence uses."""

    #: The term itself: the form it takes in the sentence.
    surface: str
    #: The lemmas of the tokens it covers.
    lemma: str
    #: The Wiktionary pages this occurrence matched, the form's own entry
    #: first, then its lemma's, then the rest. Definition fetching picks from
    #: these; there is more than one whenever Wiktionary has a page for the
    #: inflected form as well as for the lemma.
    entries: tuple[str, ...]
    #: Ids of the covered tokens, in sentence order.
    token_ids: tuple[int, ...]
    #: Character spans of those tokens within the sentence, so a later stage
    #: can point at this occurrence rather than at the form in the abstract.
    spans: tuple[tuple[int, int], ...] = ()
    #: Whether the term opens its sentence, so a leading capital may be an
    #: artefact of that position rather than the term's own spelling.
    sentence_initial: bool = False

    @property
    def spellings(self) -> tuple[str, ...]:
        """The form's own spellings: as written, and, where the capital is
        only the sentence start, without it.

        Which of the two the term really is depends on the sense, not on the
        position, so both are kept and definition fetching pools the entries
        they reach rather than picking one here.
        """
        if not self.sentence_initial:
            return (self.surface,)
        lowered = decapitalize(self.surface)
        return (self.surface,) if lowered == self.surface else (self.surface, lowered)


def extract(
    sentence: Any, index: TitleIndex, *, join_particles: bool = False
) -> list[Term]:
    """Extract the terms of one parsed sentence.

    Every title whose tree is a subtree of the sentence's is a candidate;
    candidates that are covered by a larger candidate are then dropped, so
    ``gave himself up`` yields ``give up`` rather than ``give`` and ``up``.
    The candidates are then grouped by the tokens they cover, since one
    occurrence is one term however many pages Wiktionary spells it under.
    A term the sentence uses twice in the same form is reported once.
    """
    matches: dict[frozenset[int], set[str]] = {}
    for root in trees.sentence_tree(sentence, join_particles=join_particles):
        for node in root.walk():
            for title in node.labels & index.words:
                matches.setdefault(_covered_by_label(node, title), set()).add(title)
            for title, tree in index.phrases_rooted_at(node.labels):
                covered = trees.match(tree, node)
                if covered is not None:
                    matches.setdefault(covered, set()).add(title)

    words = {word.id: word for word in sentence.words}
    punctuation = {word.id for word in sentence.words if word.upos == "PUNCT"}
    initial = trees.sentence_initial_ids(list(sentence.words))
    base = sentence.tokens[0].start_char if sentence.tokens else 0
    kept = [
        covered
        for covered in matches
        if not covered <= punctuation
        and not any(covered < other for other in matches)
    ]
    kept.sort(key=min)

    terms: list[Term] = []
    seen: set[str] = set()
    for covered in kept:
        term = _term(matches[covered], covered, words, initial, base)
        if term.surface not in seen:
            seen.add(term.surface)
            terms.append(term)
    return terms


def _covered_by_label(node: trees.Node, label: str) -> frozenset[int]:
    """The tokens a single-node title covers, particle included if it matched."""
    covered = set(node.tokens)
    for other, extra in node.label_tokens:
        if other == label:
            covered |= extra
    return frozenset(covered)


def _spans(tokens: list[Any], base: int) -> tuple[tuple[int, int], ...]:
    """Sentence-relative spans of ``tokens``, one per underlying token.

    A multiword token expands into several words sharing one span -- Spanish
    ``del`` is ``de`` and ``el`` -- so spans are deduplicated and ordered.
    """
    spans = set()
    for word in tokens:
        token = getattr(word, "parent", None) or word
        start, end = token.start_char, token.end_char
        if start is None or end is None:
            continue
        spans.add((start - base, end - base))
    return tuple(sorted(spans))


def decapitalize(text: str) -> str:
    """``text`` without a leading capital."""
    if not text[:1].isupper():
        return text
    return text[:1].lower() + text[1:]


def _term(
    entries: set[str],
    covered: frozenset[int],
    words: dict[int, Any],
    initial: set[int],
    base: int,
) -> Term:
    ids = tuple(sorted(covered))
    tokens = [words[token_id] for token_id in ids]
    surface = " ".join(word.text for word in tokens)
    lemma = " ".join(word.lemma or word.text for word in tokens)
    term = Term(
        surface=surface,
        lemma=lemma,
        entries=(),
        token_ids=ids,
        sentence_initial=ids[0] in initial,
        spans=_spans(tokens, base),
    )
    own = set(term.spellings)
    return dataclasses.replace(
        term,
        entries=tuple(
            sorted(entries, key=lambda entry: _entry_rank(entry, own, lemma))
        ),
    )


def _entry_rank(entry: str, own: set[str], lemma: str) -> tuple[int, str]:
    """The form's own page first, then its lemma's, then whatever else matched."""
    if entry in own:
        return (0, entry)
    if entry == lemma:
        return (1, entry)
    return (2, entry)

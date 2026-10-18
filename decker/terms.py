"""Term extraction: which Wiktionary entries a sentence is made of."""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from typing import Any

from decker import trees
from decker.console import VERBOSE, log
from decker.languages import joiner_of, respellings, spacer_of, unspaced
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
    #: Whether the term opens its sentence or its line, so a leading capital
    #: may be an artefact of that position rather than the term's own
    #: spelling. A line counts because lyrics and captions are lineated and
    #: unpunctuated, and the parser reads several of their lines as one
    #: sentence -- see :func:`decker.trees.positional_capital_ids`.
    positional_capital: bool = False
    #: The parse's part of speech for the term's head token, as a UD tag:
    #: `NOUN`, `ADP`, `VERB`. The sentence's own grammar, which is a thing
    #: nothing downstream had -- sense disambiguation was choosing between a
    #: preposition and the name of a letter with only the sentence to go on.
    upos: str = ""
    #: The morphological categories the parse marks on the tokens this term
    #: covers, by UD's names for them and without their values: `Case`,
    #: `Number`, `Gender`. What the *values* are is this occurrence's
    #: business; which categories exist at all is the language's, and that is
    #: what the rules stage is given so it does not write a rule about
    #: feminine nouns in Turkish.
    features: tuple[str, ...] = ()
    #: The dictionary's other spellings of this same form, where the text's
    #: own is not one it keeps: `грез` is in the dictionary as `грёз`, the
    #: diaeresis being a mark Russian prints only sometimes. The form the
    #: reader met, under the spelling the entry is titled with, so
    #: :attr:`spellings` carries it and the card is fronted with it.
    respelled: tuple[str, ...] = ()
    #: Wiktionary's own spelling of this form as a bound morpheme, where the
    #: term is one and the dictionary has it: `ל` in the text is `ל־` on the
    #: page. The same form under the dictionary's convention rather than
    #: another word, so :attr:`spellings` carries it and definition fetching
    #: pools its senses with the plain spelling's instead of ranking one
    #: behind the other.
    joined: str = ""

    @property
    def spellings(self) -> tuple[str, ...]:
        """The form's own spellings: as written, without a sentence-initial
        capital, and as a bound morpheme where it is one.

        Which of them the term really is depends on the sense, not on the
        position and not on the dictionary's typography, so they are all kept
        and definition fetching pools the entries they reach rather than
        picking one here.
        """
        found = [self.surface]
        if self.positional_capital:
            lowered = decapitalize(self.surface)
            if lowered != self.surface:
                found.append(lowered)
        if self.joined:
            found.append(self.joined)
        found.extend(self.respelled)
        return tuple(found)


def extract(
    sentence: Any,
    index: TitleIndex,
    *,
    join_particles: bool = False,
    lang: str = "",
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
    respell = (lambda label: respellings(label, lang)) if lang else None
    #: A phrase may skip tokens where words are spaced -- `gave himself up` is
    #: `give up` -- but not where they are not: an unspaced title is a word,
    #: and its pieces are written side by side or it is not there. Without
    #: this a compound's parse matches any two tokens that happen to hang off
    #: each other the same way.
    adjacent = not unspaced(lang)
    words = {word.id: word for word in sentence.words}
    for root in trees.sentence_tree(
        sentence, join_particles=join_particles, respell=respell
    ):
        for node in root.walk():
            for title in node.labels & index.words:
                matches.setdefault(_covered_by_label(node, title), set()).add(title)
            for title, tree in index.phrases_rooted_at(node.labels):
                covered = trees.match(tree, node)
                if covered is not None and (
                    adjacent or (_contiguous(covered) and _whole(covered, words))
                ):
                    matches.setdefault(covered, set()).add(title)

    punctuation = {word.id for word in sentence.words if word.upos == "PUNCT"}
    numerals = {word.id for word in sentence.words if _is_number(word.text)}
    if numerals:
        #: Named rather than only counted: this is the one drop decker makes
        #: without asking anything, so a run has to be able to show what it
        #: took. A token listed here that is not a number is a bug in
        #: :func:`_is_number` and nothing else will report it.
        written = ", ".join(
            dict.fromkeys(words[one].text for one in sorted(numerals) if one in words)
        )
        log(f"[decker] dropped as numbers: {written}", level=VERBOSE, kind="dropped")
    initial = trees.positional_capital_ids(sentence)
    base = sentence.tokens[0].start_char if sentence.tokens else 0
    kept = [
        covered
        for covered in matches
        if not covered <= punctuation
        and not covered <= numerals
        and not any(covered < other for other in matches)
    ]
    #: A word no title covers is a term too, with no entries. Before
    #: 2026-10-18 it was simply never one: `タオ`, a character's name, has no
    #: page, so it reached neither the deck nor the unknown-words stage nor a
    #: line of the log, while the `さん` after it was carded. Now it goes to
    #: the stage that asks what a word with no entry is. Neighbouring words
    #: with no title are one term, since that is what a name of several words
    #: looks like. Not even a token the parser calls a symbol is dropped here:
    #: it tagged `っす` one, and whether a token is a word is the model's call.
    covered_somewhere = set().union(*matches) if matches else set()
    for run in _runs(
        word.id for word in sentence.words
        if word.id not in covered_somewhere
        and word.id not in punctuation | numerals
    ):
        matches[run] = set()
        kept.append(run)
    kept.sort(key=min)

    joiner = joiner_of(lang)
    terms: list[Term] = []
    seen: set[str] = set()
    for covered in kept:
        bound = _bound_title(covered, words, joiner, index) if joiner else ""
        term = _term(
            matches[covered] | ({bound} if bound else set()),
            covered,
            words,
            initial,
            base,
            joined=bound,
            lang=lang,
        )
        if term.surface not in seen:
            seen.add(term.surface)
            terms.append(term)
    return terms


def _runs(ids) -> list[frozenset[int]]:
    """Token ids grouped into runs of consecutive ones."""
    runs: list[list[int]] = []
    for one in sorted(ids):
        if runs and one == runs[-1][-1] + 1:
            runs[-1].append(one)
        else:
            runs.append([one])
    return [frozenset(run) for run in runs]


def _contiguous(covered: frozenset[int]) -> bool:
    """Whether ``covered`` is a run of adjacent token ids."""
    return max(covered) - min(covered) + 1 == len(covered)


#: The tags, in the UniDic set Japanese is tagged with, of a token that belongs
#: to the word before it and of one that belongs to the word after.
_SUFFIX = "接尾辞"
_PREFIX = "接頭辞"


def _whole(covered: frozenset[int], words: dict[int, Any]) -> bool:
    """Whether an unspaced run starts and ends at the edges of words.

    A run that opens on a suffix starts inside the word before it: `お前ら` +
    `に` is *to you lot*, and `らに` was matched as the title of an obsolete
    name for a plant. A run that closes on a prefix ends inside the next.
    """
    ids = sorted(covered)
    first, last = words.get(ids[0]), words.get(ids[-1])
    return not (
        (first is not None and (first.xpos or "").startswith(_SUFFIX))
        or (last is not None and (last.xpos or "").startswith(_PREFIX))
    )


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


def _bound_title(
    covered: frozenset[int], words: dict[int, Any], joiner: str, index: TitleIndex
) -> str:
    """The title this term has as a bound morpheme, if it has one.

    A clitic is what the tokenizer split *off*: a word of a multiword token
    that is not the token's last. A word standing on its own is not one
    however short it is, so `ל` used as a noun keeps the letter's page and
    only the prefix reaches the preposition's. The title has to exist for it
    to be offered -- `של־` does not, and `של` is a free word anyway.
    """
    if len(covered) != 1:
        return ""
    word = words[next(iter(covered))]
    siblings = list(getattr(getattr(word, "parent", None), "words", ()) or ())
    if len(siblings) < 2 or siblings[-1].id == word.id:
        return ""
    title = f"{word.text}{joiner}"
    return title if title in index.words else ""


def _term(
    entries: set[str],
    covered: frozenset[int],
    words: dict[int, Any],
    initial: set[int],
    base: int,
    *,
    joined: str = "",
    lang: str = "",
) -> Term:
    ids = tuple(sorted(covered))
    tokens = [words[token_id] for token_id in ids]
    spacer = spacer_of(lang)
    surface = spacer.join(word.text for word in tokens)
    if spacer:
        lemma = spacer.join(word.lemma or word.text for word in tokens)
    else:
        #: An unspaced compound inflects at its end, so only the last token's
        #: lemma is the compound's: `出回ったら` is `出` and `回る`, the
        #: dictionary's `出回る`, and every token's lemma would be `出る回る`.
        lemma = "".join(word.text for word in tokens[:-1]) + (
            tokens[-1].lemma or tokens[-1].text
        )
    term = Term(
        surface=surface,
        lemma=lemma,
        entries=(),
        token_ids=ids,
        positional_capital=ids[0] in initial,
        spans=_spans(tokens, base),
        upos=_head(tokens).upos or "",
        features=_features(tokens),
        joined=joined,
    )
    #: Only a respelling the dictionary actually has is the term's own: the
    #: candidates are generated blind, and one that matched no title is a
    #: string this occurrence has nothing to do with.
    term = dataclasses.replace(
        term,
        respelled=tuple(
            spelling
            for base_spelling in term.spellings
            for spelling in respellings(base_spelling, lang)
            if spelling in entries
        ),
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


#: The separators a number is written with, by the conventions decker has been
#: run over: `17,5` and `17.5` are the same number, and `1 000` and `1,000` are
#: the same thousand.
_NUMERIC = str.maketrans({",": ".", "\u00a0": "", "\u202f": "", " ": ""})


def _is_number(text: str) -> bool:
    """Whether a token is a number written in digits, and so not a word.

    Written in digits: `11`, `1758`, `17,5`, `-3.6`, `1 000`. Not `dos`, not
    `二十`, not `第一` -- a numeral spelled out is vocabulary, and a learner
    needs it as much as any other word. The design's term is "a word of the
    text", and 1758 is not one: it has no entry, no sense to choose and no
    lemma, and until this it cost a title lookup, a line of stderr and a place
    in the coverage figure. Nine of the survey's ten languages had some.

    A digit inside a word leaves it alone -- `COVID-19`, `1º`, `x86` -- since
    those are spelled, said and learned.
    """
    candidate = text.strip().translate(_NUMERIC)
    if not candidate:
        return False
    try:
        float(candidate)
    except ValueError:
        return False
    #: `float` takes `nan` and `inf`, which are words in some texts and
    #: numbers in none of them.
    return any(character.isdigit() for character in candidate)


def _head(tokens: list[Any]) -> Any:
    """The token the others of a term hang off.

    A term is one word as often as not, and then this is that word. Where it
    is a phrase -- `gave up`, `tener que` -- the part of speech that describes
    the whole of it is the head's, so the token whose own head lies outside
    the term is the one asked. The first token answers for a term whose head
    is not in the parse at all, which a cycle or a fragment can produce.
    """
    covered = {token.id for token in tokens}
    for token in tokens:
        if getattr(token, "head", 0) not in covered:
            return token
    return tokens[0]


def _features(tokens: list[Any]) -> tuple[str, ...]:
    """The names of the morphological categories the parse marks on ``tokens``.

    Stanza writes them as `Case=Dat|Gender=Fem|Number=Sing`; the halves before
    the equals signs are what this is, sorted and without repeats.
    """
    found = set()
    for token in tokens:
        for feature in (getattr(token, "feats", None) or "").split("|"):
            name, _, value = feature.partition("=")
            if name and value:
                found.add(name)
    return tuple(sorted(found))

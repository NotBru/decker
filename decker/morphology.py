"""Morphological rules: the regularity behind a form, learned once.

A text is mostly inflected words, and definition fetching gives each of them a
card of its own -- `conocí` explained as "first/third-person singular preterite
indicative of conocer". The tenth such card teaches nothing the second did not:
what a learner needs is the *rule*, once, and then a handful of instances of it.
That is what the design asks for here.

A rule takes a base word to a feature bundle -- Wiktionary's form-of prose,
normalized to the concepts it links -- and is represented by the first word
decker saw obeying it. Several rules per bundle are expected and correct: the
Spanish gerund is `-ando` for `-ar` verbs and `-iendo` for the others, which is
two rules with one bundle. A word that obeys none of them is irregular, gets no
rule, and keeps its own card forever, which is exactly what an irregular form
asks of a learner.

The model is asked two questions per new word, in this order, and neither is
asked when the answer cannot change anything: does one of the rules already
written for this bundle produce this word, and if not, is there a regular rule
here at all. The answers are cached like every other model answer, and the
rules themselves outlive the run in a small database of their own -- they are
knowledge about the language, not about a deck, and the next text in the same
language starts with every rule the last one worked out.
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

from decker.languages import name_of
from decker.ollama import DEFAULT_MODEL, Session

#: What a rule card is called, the way a concept card is called `Concept: `.
#: The rule is not a word of the language being learned, and a card titled
#: with its feature bundle alone would read as one.
RULE_PREFIX = "Rule: "

#: How many instances of a rule are kept before the culling starts, and how
#: many kept instances it takes to halve the frequency again. The design's
#: numbers: keep the first 4, then halve every 4 shown.
FIRST_KEPT = 4
HALVE_EVERY = 4

#: How many instances the explanation card waits for. The design's: a rule
#: stated after one example is a generalization from one example, and the
#: learner has no reason yet to want it.
EXAMPLES_BEFORE_RULE = 2

APPLIES_SCHEMA = {
    "type": "object",
    "properties": {"rule": {"type": "integer"}},
    "required": ["rule"],
}

REGULAR_SCHEMA = {
    "type": "object",
    "properties": {
        "regular": {"type": "boolean"},
        "rule": {"type": "string"},
    },
    "required": ["regular", "rule"],
}

#: Fixed instructions first and the variable parts last, the same shape as the
#: disambiguation and translation prompts and for the same reason: ollama keeps
#: the prefill of a shared prefix between calls, and on a laptop's CPU that
#: prefix is most of the cost.
PROMPT_APPLIES = """\
You are helping build language-learning cards from a text in {language}.

Below are the morphological rules already written for one feature bundle --
one way each of getting from a base word to that bundle -- with the word each
was written from. You will be shown another word of the same bundle.

Reply with the number of the rule this new word obeys, or 0 if none of them
does. A word obeys a rule when applying that rule to its base word yields
exactly this word, with no further change; a word that needs an extra change
-- a different stem, a consonant that shifts, an accent that is not the rule's
-- obeys none of them, and 0 is the right answer.

Feature bundle: {bundle}
Rules already written:
{rules}

Base word: {base}
Word: {surface}

Reply with one number: the rule this word obeys, or 0 for none.
"""

PROMPT_REGULAR = """\
You are helping build language-learning cards from a text in {language}.

You will be shown a base word, a word derived from it, and what the derivation
expresses. Say whether the derivation is REGULAR -- whether a learner could
produce this word from the base word by a rule that holds for a whole class of
words -- or whether this word is irregular and simply has to be learned.

If it is regular, write the rule in one or two plain sentences: which class of
base words it applies to, and what is done to them. Name the endings involved.
Write it for a learner who has met neither of these two words, so state the
rule in general -- do not answer with these words as the reason. Write it in
{source}. If it is irregular, say so and leave the rule empty.
{inventory}
Base word: {base}
Word: {surface}
What the derivation expresses: {bundle}
Wiktionary's own line: {prose}

Answer whether it is regular, and if so, the rule.
"""

#: What a rule may be stated over, and what it may not. The survey found the
#: model writing "for feminine nouns, add the ending -in to form the genitive
#: singular" in Turkish and "for masculine nouns ending in a consonant" in
#: Hungarian -- two languages with no grammatical gender at all. The endings
#: were often right and the class was invented, which is the worst shape a
#: wrong card can take: it teaches a distinction the language does not make.
#:
#: The parse already knows. Stanza marks the categories a language inflects
#: for on every word it reads, so a category that is marked nowhere in a whole
#: text is one the language does not have -- for these six, at least, which
#: are marked on nearly every word that could carry them. The rarer ones
#: (aspect, voice, animacy, degree) are left out in both directions: absent
#: from a 2,500-character sample they may be absent from the sample only, and
#: a prompt that says so with confidence would be worse than one that says
#: nothing.
#:
#: Mood was in this list and was taken out, which is what the list being short
#: is for. Run over the survey's ten samples it came back absent for Dutch and
#: Hebrew, both of which have an imperative: UD treebanks mark Mood sparsely,
#: so that absence is the treebank's habit and not the language's. The other
#: six came back absent only where the language really has nothing -- gender
#: in Hungarian, Turkish, Japanese and Chinese, definiteness in Turkish, tense
#: in Chinese -- and Japanese, whose parse marks none of the six, is told
#: nothing at all rather than told that it has no grammar.
PERVASIVE = {
    "Gender": "grammatical gender",
    "Number": "number",
    "Case": "case",
    "Person": "person",
    "Tense": "tense",
    "Definite": "definiteness",
}

#: The wording is measured, not written once. The first version ended "an
#: ending that applies to feminine nouns cannot be the rule in a language
#: without gender", and handing a small model the example was handing it the
#: words: `gemma3:4b` wrote four gendered Turkish rules with that paragraph
#: and none without it, and `qwen3:14b` wrote one with and none without. The
#: version below says the same thing without naming a class. Over eight
#: model-language pairs (four models, Turkish and Hungarian) the gendered
#: rules went 8 with no paragraph, 7 with the first wording, 5 with this one
#: -- and to zero for `gemma4:latest`, whose invention started all this.
INVENTORY = """
Of the categories a rule like this is usually stated over, the parse of this
text marks {present} in {language}, and marks {absent} nowhere at all. State
the rule only over categories the language has: a class of base word that this
language does not distinguish cannot be the condition of a rule, however right
the ending is.
"""


@dataclass(frozen=True)
class Rule:
    """One way of getting from a base word to a feature bundle."""

    #: The feature bundle, canonicalized and sorted: the rule's identity, and
    #: what "the rules for this bundle" is asked against. Sorted because the
    #: order a definition names its features in is the definition's business --
    #: `first-person singular preterite` and `preterite first-person singular`
    #: are one bundle.
    bundle: tuple[str, ...]
    #: The bundle as a card can show it: Wiktionary's own form-of prose, minus
    #: the base word it hangs on. Readable where `bundle` is canonical.
    label: str
    #: The word the rule was written from, and the second half of its identity:
    #: one bundle has as many rules as the language has classes of base word.
    representative: str
    #: The word the representative is derived from.
    base: str
    #: The Wiktionary page the representative was glossed from. A form met as
    #: `enrulada` can be glossed from `enrulado`, so the word in the text is
    #: not always a title, and a card's credit has to link one that is.
    entry: str
    #: The rule itself, as the model wrote it, in the edition's language.
    description: str
    #: The language this rule is about, as a code.
    language: str
    #: Which model wrote the description, kept as provenance. A rule is reused
    #: whoever wrote it -- it is a fact about the language -- but a run that
    #: finds a strange one should be able to see where it came from.
    model: str = ""

    @property
    def key(self) -> tuple[str, tuple[str, ...], str]:
        """What makes this rule that rule and not another."""
        return (self.language, self.bundle, self.representative)

    def title(self) -> str:
        """What the rule's card is called.

        The representative is part of the title because it is part of the
        identity: `-ar` and `-er` gerunds are two cards with one bundle, and a
        learner meeting the second needs to see at a glance that it is not the
        first one again.
        """
        return f"{RULE_PREFIX}{self.label} ({self.representative})"


@dataclass
class RuleBook:
    """Every rule worked out for one language, kept between runs.

    Under the cache, because it is derived data: deleting it costs the model
    calls that made it and nothing else. It is *not* where the culling counts
    live -- those belong to a deck, and a cache a deck depended on would no
    longer be a cache.
    """

    lang: str
    path: Path
    rules: list[Rule] = field(default_factory=list)

    @classmethod
    def load(cls, lang: str) -> "RuleBook":
        path = _book_path(lang)
        rules: list[Rule] = []
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            payload = []
        for record in payload if isinstance(payload, list) else []:
            try:
                rules.append(
                    Rule(
                        bundle=tuple(record["bundle"]),
                        label=record["label"],
                        representative=record["representative"],
                        base=record["base"],
                        entry=record.get("entry", ""),
                        description=record["description"],
                        language=record.get("language", lang),
                        model=record.get("model", ""),
                    )
                )
            except (KeyError, TypeError):
                continue  # a record from a future shape, or a truncated one
        return cls(lang=lang, path=path, rules=rules)

    def matching(self, bundle: tuple[str, ...]) -> list[Rule]:
        """The rules for one feature bundle, which is all a new word can obey.

        Bru's scoping decision: "any of the existing rules" means the rules
        sharing this word's feature bundle and language, not the whole table.
        A rule for the diminutive has nothing to say about a preterite, and
        asking a small model to rule it out is a call spent to learn nothing.
        """
        return [rule for rule in self.rules if rule.bundle == bundle]

    def add(self, rule: Rule) -> None:
        """Write one rule down, and save at once.

        At once rather than at the end of the run: the run is minutes of local
        inference on a machine that has been known to lose power mid-call, and
        a rule is a model call that does not have to be spent twice.
        """
        self.rules.append(rule)
        self.save()

    def save(self) -> None:
        """Keep the book, or carry on without keeping it."""
        payload = [
            {
                "bundle": list(rule.bundle),
                "label": rule.label,
                "representative": rule.representative,
                "base": rule.base,
                "entry": rule.entry,
                "description": rule.description,
                "language": rule.language,
                "model": rule.model,
            }
            for rule in self.rules
        ]
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            #: Written beside and moved into place, the way model answers are:
            #: an interrupted run leaves the previous book, never half of one.
            temporary = self.path.with_suffix(".part")
            temporary.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            temporary.replace(self.path)
        except OSError:
            pass


def _listed(words: list[str]) -> str:
    """``a, b and c``: a list as a sentence says one."""
    if len(words) == 1:
        return words[0]
    return f"{', '.join(words[:-1])} and {words[-1]}"


def _book_path(lang: str) -> Path:
    from decker.wiktionary import cache_dir

    return cache_dir() / "rules" / f"{lang}.json"


@dataclass(frozen=True)
class Outcome:
    """What the stage decides about one inflected word of the text."""

    #: Whether this occurrence still gets a card of its own. False is the
    #: design's culling: the rule covers it, the learner has seen enough of
    #: them, and the base word's card stays either way.
    keep: bool = True
    #: The rule it obeys, if any. Absent for an irregular form, and for every
    #: form at all when the stage is off or the model cannot be reached.
    rule: Rule | None = None


@dataclass
class Morphology:
    """The rules stage: what obeys what, and how much of it reaches the deck."""

    lang: str
    model: str = DEFAULT_MODEL
    host: str | None = None
    enabled: bool = True
    #: Ask the model again even when the answer is cached.
    refresh: bool = False
    session: Session = field(init=False)
    book: RuleBook = field(init=False)
    #: Per rule, how many instances have reached the deck and how many have
    #: been passed over since the last one that did. Per run, deliberately:
    #: they pace one deck, and a second deck over the same text is a second
    #: learner's first week, not a continuation of the first's.
    shown: dict[tuple, int] = field(default_factory=dict, init=False)
    pending: dict[tuple, int] = field(default_factory=dict, init=False)
    #: The gloss indexes of the first instances of each rule that reached the
    #: deck, up to the number the explanation card waits for.
    examples: dict[tuple, list[int]] = field(default_factory=dict, init=False)
    #: Rules whose explanation card has already been made this run.
    explained: set[tuple] = field(default_factory=set, init=False)
    #: Words already asked about, so a form met twice is one pair of calls.
    decided: dict[tuple, Rule | None] = field(default_factory=dict, init=False)
    #: How many instances were culled, for the run's report.
    dropped: int = 0
    #: How many rules this run wrote that the book did not already hold.
    written: int = 0
    #: The morphological categories the parse marks anywhere in the text, by
    #: UD's names for them. Term extraction reads them off every word it
    #: covers; what they are for is :data:`INVENTORY`.
    categories: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        self.session = Session(
            model=self.model,
            host=self.host,
            refresh=self.refresh,
            what="morphological rules",
            fallback="a card for every inflected form, and no rule cards",
        )
        self.book = RuleBook.load(self.lang)

    def consider(
        self,
        *,
        surface: str,
        base: str,
        bundle: tuple[str, ...],
        label: str,
        prose: str,
        entry: str = "",
    ) -> Outcome:
        """Decide what becomes of one inflected occurrence.

        The rule is found or written first, because the culling is a property
        of the rule: an irregular form obeys nothing, is covered by nothing,
        and is therefore never culled.
        """
        if not self.enabled or not bundle or not base:
            return Outcome()
        rule = self._rule_for(
            surface=surface, base=base, bundle=bundle, label=label, prose=prose, entry=entry
        )
        if rule is None:
            return Outcome()
        return Outcome(keep=self._cull(rule), rule=rule)

    def _rule_for(
        self,
        *,
        surface: str,
        base: str,
        bundle: tuple[str, ...],
        label: str,
        prose: str,
        entry: str,
    ) -> Rule | None:
        memo = (self.lang, bundle, base, surface)
        if memo not in self.decided:
            self.decided[memo] = self._decide(
                surface=surface,
                base=base,
                bundle=bundle,
                label=label,
                prose=prose,
                entry=entry,
            )
        return self.decided[memo]

    def _decide(
        self,
        *,
        surface: str,
        base: str,
        bundle: tuple[str, ...],
        label: str,
        prose: str,
        entry: str,
    ) -> Rule | None:
        known = self.book.matching(bundle)
        if known:
            #: The representative of a rule obeys it by construction, and
            #: asking would spend a call to be told so.
            for rule in known:
                if rule.representative == surface and rule.base == base:
                    return rule
            chosen = self._ask_applies(
                surface=surface, base=base, bundle=bundle, rules=known
            )
            if chosen is not None:
                return chosen
        return self._ask_regular(
            surface=surface,
            base=base,
            bundle=bundle,
            label=label,
            prose=prose,
            entry=entry,
        )

    def _ask_applies(
        self,
        *,
        surface: str,
        base: str,
        bundle: tuple[str, ...],
        rules: list[Rule],
    ) -> Rule | None:
        listing = "\n".join(
            f"{number}. (from {rule.representative}, base {rule.base}) {rule.description}"
            for number, rule in enumerate(rules, start=1)
        )
        answer = self.session.ask(
            PROMPT_APPLIES.format(
                language=name_of(self.lang),
                bundle=", ".join(bundle),
                rules=listing,
                base=base,
                surface=surface,
            ),
            APPLIES_SCHEMA,
        )
        if not answer:
            return None
        try:
            chosen = int(answer.get("rule", 0))
        except (TypeError, ValueError):
            return None
        if 1 <= chosen <= len(rules):
            return rules[chosen - 1]
        return None

    def _ask_regular(
        self,
        *,
        surface: str,
        base: str,
        bundle: tuple[str, ...],
        label: str,
        prose: str,
        entry: str,
    ) -> Rule | None:
        from decker.translation import SOURCE_LANGUAGE

        answer = self.session.ask(
            PROMPT_REGULAR.format(
                language=name_of(self.lang),
                source=SOURCE_LANGUAGE,
                inventory=self._inventory(),
                base=base,
                surface=surface,
                bundle=", ".join(bundle),
                prose=prose,
            ),
            REGULAR_SCHEMA,
        )
        if not answer or not answer.get("regular"):
            return None
        description = answer.get("rule")
        if not isinstance(description, str) or not description.strip():
            #: Regular, and no rule written: nothing to teach, so the form is
            #: treated as irregular rather than given an empty card.
            return None
        rule = Rule(
            bundle=bundle,
            label=label,
            representative=surface,
            base=base,
            entry=entry or surface,
            description=description.strip(),
            language=self.lang,
            model=self.model,
        )
        self.book.add(rule)
        self.written += 1
        return rule

    def _inventory(self) -> str:
        """What to tell the model about the language's categories, if anything.

        Nothing at all when every pervasive category is marked somewhere: a
        language that has all seven cannot have a rule stated over one it does
        not have, and a paragraph spent saying so is a paragraph the model has
        to read on every call. Nothing, too, when the parse marked none of
        them -- Chinese and Japanese mark nothing here, and the honest reading
        of that is that the parse has nothing to say, not that the language
        has no grammar.
        """
        marked = set(self.categories)
        present = [word for name, word in PERVASIVE.items() if name in marked]
        absent = [word for name, word in PERVASIVE.items() if name not in marked]
        if not present or not absent:
            return ""
        return INVENTORY.format(
            language=name_of(self.lang),
            present=_listed(present),
            absent=_listed(absent),
        )

    def _cull(self, rule: Rule) -> bool:
        """Whether this instance of ``rule`` still reaches the deck.

        The design's pacing: the first four instances all do, and after that
        the frequency halves every four that do -- one in two, then one in
        four, then one in eight. A rule met all through a long text therefore
        costs a handful of cards rather than a card a paragraph, and the ones
        it does cost are spread over the whole of it.
        """
        key = rule.key
        shown = self.shown.get(key, 0)
        period = 1 if shown < FIRST_KEPT else 2 ** (shown // HALVE_EVERY)
        pending = self.pending.get(key, 0) + 1
        if pending < period:
            self.pending[key] = pending
            self.dropped += 1
            return False
        self.pending[key] = 0
        self.shown[key] = shown + 1
        return True

    def example(self, rule: Rule, index: int) -> tuple[int, ...] | None:
        """Record an instance that reached the deck; say when the rule can be told.

        The explanation card depends on the first two instances, so it is made
        at the second one and not before -- which also puts it after them in
        the gloss list, where a dependency has to be for deck construction to
        find the card that introduces it.
        """
        seen = self.examples.setdefault(rule.key, [])
        if len(seen) < EXAMPLES_BEFORE_RULE and index not in seen:
            seen.append(index)
        if rule.key in self.explained or len(seen) < EXAMPLES_BEFORE_RULE:
            return None
        self.explained.add(rule.key)
        return tuple(seen)

    def report(self) -> None:
        """Say what the stage did, when it did anything at all."""
        if not self.enabled:
            return
        if self.explained:
            print(
                f"[decker] {len(self.explained)} of them are morphological rules "
                f"({self.written} written this run; {len(self.book.rules)} known "
                f"for {self.lang!r})",
                file=sys.stderr,
            )
        if self.dropped:
            print(
                f"[decker] {self.dropped} inflected forms left out, covered by "
                "a rule already shown (their base words are still taught)",
                file=sys.stderr,
            )


def label_of(prose: str, base: str) -> str:
    """Wiktionary's form-of line, without the word it hangs on.

    "first/third-person singular preterite indicative of conocer" is a bundle
    and a base word in one sentence; the bundle is what a rule is about, and
    the base word is already on the card's other side.
    """
    stripped = re.sub(
        rf"\s+of\s+{re.escape(base)}\b.*$", "", prose.strip(), flags=re.IGNORECASE
    )
    return (stripped or prose.strip()).rstrip(" .,;:")

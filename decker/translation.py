"""Translation: a gloss written in the mother language.

Glosses are quoted from a Wiktionary edition, so they are written in that
edition's language -- English, for v1's ``en``. A learner whose mother tongue
is something else needs the same gloss in it, which the design puts in deck
construction and v1 puts through ollama, the same way sense disambiguation
goes through it.

The mother tongue is named by a code, the way every other language decker is
told about is; the prompt below is the only thing that wants it as a word, and
:mod:`decker.languages` is where the code becomes one.

Only the prose is translated. An example arrives as a pair -- the sentence in
the target language, the edition's rendering of it -- and only the rendering
is sent: the sentence never reaches the model, so no answer can rewrite the
very thing the card is teaching. That holds for every example, including the
ones whose sentence contains the em dash the two halves are shown with, which
is why :class:`decker.pages.Example` keeps them apart rather than joining them
and cutting the string up again here. The headword and the forms a definition
names are still asked to survive untouched, because they are inside the
definition and cannot be held back from it.
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter
from dataclasses import dataclass, field

from decker.languages import name_of
from decker.ollama import DEFAULT_MODEL, Session
from decker.pages import Example

#: The language a gloss arrives in: the edition's own, which v1 fixes at the
#: English Wiktionary. A mother language other than this one is what makes
#: translation happen at all. The code is what decker is told and what the
#: comparison is made on; the name is for the prompt, and only there.
SOURCE_LANG = "en"
SOURCE_LANGUAGE = "English"

SCHEMA = {
    "type": "object",
    "properties": {
        "definition": {"type": "string"},
        "examples": {"type": "array", "items": {"type": "string"}},
        "etymology": {"type": "string"},
    },
    #: The etymology is required, and that is the whole of what once looked
    #: like a translation the model got wrong. Left optional, ollama's
    #: structured output let the model omit the field; an omitted field is an
    #: empty one, an empty one falls back to the text that was sent, and the
    #: card carried the English original with nothing in the run saying so.
    #: Required, the same model translates every one of them.
    "required": ["definition", "examples", "etymology"],
}

#: Fixed instructions first, the gloss last, so that consecutive calls share
#: as long a prefix as ollama can keep prefilled between them -- the same
#: shape, and for the same reason, as the disambiguation prompts.
PROMPT = """\
You are helping build language-learning cards for a speaker of {mother}, from
a dictionary written in {source} that teaches {target}.

You will be shown one definition, the {source} renderings of the examples
under it, and its etymology -- all of it written in {source}. Put all of it
into {mother}, keeping the meaning exact and the wording plain and short.

The headword and any form of it the definition names are quoted from {target}
and stay exactly as they are; translate the {source} around them. Answer with
the same number of examples, in the same order. If there is no etymology,
answer with an empty one.

Definition: {definition}
Examples: {examples}
Etymology: {etymology}

Answer in {mother}.
"""


@dataclass
class Translator:
    """Puts a gloss into the mother language, or leaves it as it came."""

    mother_lang: str = SOURCE_LANG
    model: str = DEFAULT_MODEL
    host: str | None = None
    enabled: bool = True
    session: Session = field(init=False)
    #: Glosses already translated this run, keyed by the text asked about: a
    #: sense met by two terms is one call, not two.
    done: dict[tuple, tuple] = field(default_factory=dict, init=False)
    #: Fields that reached a card in the source language anyway, by kind. A
    #: model that answers with nothing, or with the very text it was handed,
    #: leaves prose the fallbacks below then restore -- correctly, since an
    #: untranslated right sentence beats a translated wrong one, but silently.
    #: Counting them is what lets a run say so instead of the reader finding
    #: out from the cards.
    kept: Counter[str] = field(default_factory=Counter, init=False)

    def __post_init__(self) -> None:
        self.session = Session(
            model=self.model,
            host=self.host,
            what="translation",
            fallback=f"leaving the cards in {SOURCE_LANGUAGE}",
        )

    @property
    def needed(self) -> bool:
        """Whether anything has to be translated at all.

        v1's mother language is the edition's, so the usual run answers no
        here and never opens a connection.
        """
        code = self.mother_lang.strip().casefold()
        return self.enabled and bool(code) and code != SOURCE_LANG

    def gloss(
        self,
        *,
        definition: str,
        examples: tuple[Example, ...],
        etymology: str | None,
        target_language: str,
    ) -> tuple[str, tuple[Example, ...], str | None]:
        """The three pieces of prose a gloss carries, in the mother language."""
        if not self.needed:
            return definition, examples, etymology
        key = (definition, examples, etymology, target_language)
        if key not in self.done:
            self.done[key] = self._ask(
                definition=definition,
                examples=examples,
                etymology=etymology,
                target_language=target_language,
            )
        return self.done[key]

    def _ask(
        self,
        *,
        definition: str,
        examples: tuple[Example, ...],
        etymology: str | None,
        target_language: str,
    ) -> tuple[str, tuple[Example, ...], str | None]:
        sent = tuple(
            example.rendering for example in examples if example.rendering
        )
        prompt = PROMPT.format(
            mother=name_of(self.mother_lang),
            source=SOURCE_LANGUAGE,
            target=target_language or "the target language",
            definition=definition,
            examples=json.dumps(list(sent), ensure_ascii=False),
            etymology=etymology or "(none)",
        )
        answer = self.session.ask(prompt, SCHEMA)
        if not answer or not isinstance(answer.get("definition"), str):
            #: A call that was never answered is the session's warning to
            #: make, once for the whole run; it is not this count's business.
            return definition, examples, etymology
        self._count(answer, definition=definition, sent=sent, etymology=etymology)
        return (
            answer["definition"].strip() or definition,
            _examples(answer.get("examples"), examples, sent),
            _etymology(answer.get("etymology"), etymology),
        )

    def _count(
        self,
        answer: dict,
        *,
        definition: str,
        sent: tuple[str, ...],
        etymology: str | None,
    ) -> None:
        """Tally the fields that will reach a card in the source language."""
        self.kept.update(_kept("definition", answer.get("definition"), definition))
        self.kept.update(_kept("etymology", answer.get("etymology"), etymology))
        answered = answer.get("examples")
        if not sent:
            return
        if not isinstance(answered, list) or len(answered) != len(sent):
            self.kept["examples refused"] += 1
            return
        for was, got in zip(sent, answered):
            self.kept.update(_kept("example", got, was))

    def report(self) -> None:
        """Say how much prose reached the cards untranslated, if any did."""
        if not self.kept:
            return
        parts = ", ".join(f"{count} {kind}" for kind, count in sorted(self.kept.items()))
        print(
            f"[decker] {sum(self.kept.values())} fields kept their "
            f"{SOURCE_LANGUAGE}: {parts}",
            file=sys.stderr,
        )


def _kept(field: str, answered: object, original: str | None) -> dict[str, int]:
    """Whether one field will carry its source text onto a card, and why.

    Two shapes reach a card untranslated and neither is an error: an empty
    answer, which the fallbacks below replace with what was sent, and an echo,
    which is the text that was sent handed straight back. The second is a
    well-formed string that no schema can refuse, so counting is the only
    place it can be noticed at all.
    """
    if original is None:
        return {}
    text = answered.strip() if isinstance(answered, str) else ""
    if not text:
        return {f"{field} empty": 1}
    if _MARKER.sub("", text) == original.strip():
        return {f"{field} echoed": 1}
    return {}


#: A small model copies the shape it is shown, markers and all: asked with a
#: bulleted list, qwen3:1.7b answered "- Mi tío es..." every single call. The
#: prompt shows a JSON array now, which is the shape of the answer itself, so
#: there is no marker to copy -- but a marker belongs to a list and never to a
#: sentence, so one that turns up anyway is taken off here rather than shown
#: on a card.
_MARKER = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s+")


def _examples(
    answered: object,
    examples: tuple[Example, ...],
    sent: tuple[str, ...],
) -> tuple[Example, ...]:
    """The examples with their renderings translated, or exactly as they came.

    Only the renderings were sent, so only they can come back, and each one is
    put back beside the sentence it belongs to. A model that drops or merges
    one has changed which sentence teaches what, so an answer that does not
    line up one for one is refused whole.
    """
    if not sent or not isinstance(answered, list) or len(answered) != len(sent):
        return examples
    translated = iter(answered)
    rebuilt = []
    for example in examples:
        if not example.rendering:
            rebuilt.append(example)
            continue
        answer = _MARKER.sub("", str(next(translated))).strip()
        rebuilt.append(Example(example.sentence, answer or example.rendering))
    return tuple(rebuilt)


def _etymology(answered: object, original: str | None) -> str | None:
    if original is None:
        return None
    if not isinstance(answered, str) or not answered.strip():
        return original
    return answered.strip()

"""Translation: a gloss written in the mother language.

Glosses are quoted from a Wiktionary edition, so they are written in that
edition's language -- English, for v1's ``en``. A learner whose mother tongue
is something else needs the same gloss in it, which the design puts in deck
construction and v1 puts through ollama, the same way sense disambiguation
goes through it.

Only the prose is translated. The example sentences are the target language
itself, and the headword and the forms a definition names are the very thing
being taught, so they are asked to survive untouched.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from decker.ollama import DEFAULT_MODEL, Session

#: The language a gloss arrives in: the edition's own, which v1 fixes at the
#: English Wiktionary. A mother language other than this one is what makes
#: translation happen at all.
SOURCE_LANGUAGE = "English"

SCHEMA = {
    "type": "object",
    "properties": {
        "definition": {"type": "string"},
        "examples": {"type": "array", "items": {"type": "string"}},
        "etymology": {"type": "string"},
    },
    "required": ["definition"],
}

#: Fixed instructions first, the gloss last, so that consecutive calls share
#: as long a prefix as ollama can keep prefilled between them -- the same
#: shape, and for the same reason, as the disambiguation prompts.
PROMPT = """\
You are helping build language-learning cards for a speaker of {mother}, from
a {source} dictionary that teaches {target}.

You will be shown one definition written in {source}, the examples under it,
and its etymology. Put all of it into {mother}, keeping the meaning exact and
the wording plain and short.

Anything quoted from {target} stays exactly as it is: the example sentences
themselves, the headword, and any form of it the definition names. Translate
only the {source} around them. Answer with the same number of examples, in the
same order. If there is no etymology, answer with an empty one.

Definition: {definition}
Examples:
{examples}
Etymology: {etymology}

Answer in {mother}, leaving the {target} alone.
"""


@dataclass
class Translator:
    """Puts a gloss into the mother language, or leaves it as it came."""

    mother_language: str = SOURCE_LANGUAGE
    model: str = DEFAULT_MODEL
    host: str | None = None
    enabled: bool = True
    session: Session = field(init=False)
    #: Glosses already translated this run, keyed by the text asked about: a
    #: sense met by two terms is one call, not two.
    done: dict[tuple, tuple] = field(default_factory=dict, init=False)

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
        return (
            self.enabled
            and self.mother_language.strip().casefold() != SOURCE_LANGUAGE.casefold()
        )

    def gloss(
        self,
        *,
        definition: str,
        examples: tuple[str, ...],
        etymology: str | None,
        target_language: str,
    ) -> tuple[str, tuple[str, ...], str | None]:
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
        examples: tuple[str, ...],
        etymology: str | None,
        target_language: str,
    ) -> tuple[str, tuple[str, ...], str | None]:
        prompt = PROMPT.format(
            mother=self.mother_language,
            source=SOURCE_LANGUAGE,
            target=target_language or "the target language",
            definition=definition,
            examples="\n".join(f"- {example}" for example in examples) or "- (none)",
            etymology=etymology or "(none)",
        )
        answer = self.session.ask(prompt, SCHEMA)
        if not answer or not isinstance(answer.get("definition"), str):
            return definition, examples, etymology
        return (
            answer["definition"].strip() or definition,
            _examples(answer.get("examples"), examples),
            _etymology(answer.get("etymology"), etymology),
        )


def _examples(answered: object, original: tuple[str, ...]) -> tuple[str, ...]:
    """The translated examples, or the originals if they do not line up.

    An example is a sentence and its rendering; a model that drops or merges
    one has changed which sentence teaches what, and a card that quotes the
    wrong sentence is worse than one quoting an untranslated right one.
    """
    if not isinstance(answered, list) or len(answered) != len(original):
        return original
    return tuple(
        str(translated).strip() or was for translated, was in zip(answered, original)
    )


def _etymology(answered: object, original: str | None) -> str | None:
    if original is None:
        return None
    if not isinstance(answered, str) or not answered.strip():
        return original
    return answered.strip()

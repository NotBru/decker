"""Sense disambiguation: which of a page's senses the sentence actually uses.

A Wiktionary page lists every sense a word has ever had; a card built from all
of them teaches noise. The design puts this choice in the hands of a local
model served by ollama, asked one term at a time and answering with the sense
numbers it keeps.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from decker.ollama import DEFAULT_MODEL, Session
from decker.pages import Sense

SCHEMA = {
    "type": "object",
    "properties": {
        "senses": {"type": "array", "items": {"type": "integer"}},
    },
    "required": ["senses"],
}

#: Every prompt puts its fixed instructions first and its variable parts last,
#: so that consecutive calls share as long a common prefix as possible. Ollama
#: keeps the prefill of that prefix between calls and re-reads only the tail,
#: which on a laptop's CPU is most of the cost: the answer is a handful of
#: tokens, the sense listing that precedes it is hundreds. A short restatement
#: of the task follows the listing, since instructions sitting far from the end
#: of a long prompt are the ones a small model drifts from -- it comes after
#: the prefix has already diverged, so it is free.
PROMPT = """\
You are helping build language-learning cards from a text in {language}.

You will be shown a sentence, one term occurring in it marked ⟨like this⟩, and
the numbered senses of the Wiktionary page(s) that term belongs to. Judge the
marked occurrence only: the same word elsewhere in the sentence may well be a
different one.

Reply with the numbers of the senses this occurrence actually uses. Each sense
you keep becomes a flashcard of its own, so keep as few as truly apply --
usually exactly one. Keep more only where the occurrence genuinely carries more
than one meaning at once, not merely because a sense is nearby or related. If
none fit, keep the single closest one.

Sentence: {sentence}
Term as it appears: {surface}
Numbered senses of the Wiktionary page(s) {title}:
{senses}

Reply with the numbers of the senses the marked occurrence actually uses.
"""

#: Asked when the word is not in the text at all, but is referenced by a
#: definition that describes another word in terms of it. One sense is wanted:
#: the reader needs the meaning the reference relies on, not the word's range.
PROMPT_ONE = """\
You are helping build language-learning cards from a text in {language}.

You will be shown a sentence, a word that some definition in that sentence
describes another word in terms of, and the numbered senses of that word's
Wiktionary page(s).

Reply with the number of the ONE sense that the description relies on -- the
meaning a reader has to know for that description to make sense. Exactly one
number.

Sentence: {sentence}
The word being described in terms of: "{surface}"
Numbered senses of the Wiktionary page(s) {title}:
{senses}

Reply with exactly one sense number.
"""


@dataclass
class Disambiguator:
    """Picks senses through ollama, or keeps everything when it cannot."""

    model: str = DEFAULT_MODEL
    host: str | None = None
    #: Ask the model again even when the answer is cached.
    refresh: bool = False
    enabled: bool = True
    session: Session = field(init=False)

    def __post_init__(self) -> None:
        self.session = Session(
            model=self.model,
            host=self.host,
            refresh=self.refresh,
            what="sense disambiguation",
            fallback="keeping every sense",
        )

    def keep(
        self,
        senses: tuple[Sense, ...],
        *,
        sentence: str,
        surface: str,
        title: str,
        language: str,
        parts_of_speech: tuple[str, ...] = (),
        sources: tuple[str, ...] = (),
        single: bool = False,
    ) -> tuple[Sense, ...]:
        """Return the senses worth glossing, in their original order.

        ``sources`` names the page each sense came from, so a term pooled
        from more than one spelling shows the model which entry is which.
        """
        if not self.enabled or len(senses) <= 1:
            return senses[:1] if single else senses
        listing = "\n".join(
            f"{number}. {_labelled(sense, parts_of_speech, sources, number - 1)}"
            for number, sense in enumerate(senses, start=1)
        )
        prompt = (PROMPT_ONE if single else PROMPT).format(
            language=language,
            sentence=sentence,
            surface=surface,
            title=title,
            senses=listing,
        )
        chosen = self._ask(prompt)
        if chosen is None:
            return senses[:1] if single else senses
        kept = tuple(
            sense
            for number, sense in enumerate(senses, start=1)
            if number in chosen
        ) or senses
        return kept[:1] if single else kept

    def _ask(self, prompt: str) -> set[int] | None:
        answer = self.session.ask(prompt, SCHEMA)
        if answer is None:
            return None
        try:
            return {int(number) for number in answer.get("senses", ())}
        except (TypeError, ValueError) as error:  # a schema the model bent
            self.session.warn(str(error))
            return None


def _labelled(
    sense: Sense,
    parts_of_speech: tuple[str, ...],
    sources: tuple[str, ...],
    index: int,
) -> str:
    part = parts_of_speech[index] if index < len(parts_of_speech) else ""
    source = sources[index] if index < len(sources) else ""
    if source and len(set(sources)) > 1:
        part = f"{source}, {part}" if part else source
    return f"({part}) {sense.definition}" if part else sense.definition

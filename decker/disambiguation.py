"""Sense disambiguation: which of a page's senses the sentence actually uses.

A Wiktionary page lists every sense a word has ever had; a card built from all
of them teaches noise. The design puts this choice in the hands of a local
model served by ollama, asked one term at a time and answering with the sense
numbers it keeps.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass

from decker.pages import Sense

#: The model is parametrizable; this is the design's default.
DEFAULT_MODEL = "gemma4"

#: Ollama has no authentication, so it is never exposed beyond a loopback or a
#: tunnel. The fallback is ollama's own default; a host reached through a
#: tunnel -- a forwarded GPU box, say -- is named by ``OLLAMA_HOST``.
DEFAULT_HOST = "http://localhost:11434"

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
    enabled: bool = True

    def __post_init__(self) -> None:
        self._client = None
        self._warned = False
        self._thinkable = True

    def client(self):
        if self._client is None:
            import ollama

            self._client = ollama.Client(
                host=self.host or os.environ.get("OLLAMA_HOST") or DEFAULT_HOST
            )
        return self._client

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

    def _chat(self, prompt: str):
        """One call, with the model's own reasoning turned off if it has any.

        The answer is a list of numbers under a schema, so chain of thought
        buys nothing and costs everything: qwen3:1.7b spent 4222 thinking
        tokens and 80 seconds on a question it answers in 2.3 seconds without.
        Models that do not take the argument are asked again without it.
        """
        arguments = dict(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            format=SCHEMA,
            options={"temperature": 0},
        )
        if self._thinkable:
            try:
                return self.client().chat(**arguments, think=False)
            except TypeError:
                self._thinkable = False
        return self.client().chat(**arguments)

    def _ask(self, prompt: str) -> set[int] | None:
        try:
            response = self._chat(prompt)
            answer = json.loads(response["message"]["content"])
            return {int(number) for number in answer.get("senses", ())}
        except Exception as error:  # ollama down, model missing, bad JSON
            if not self._warned:
                print(
                    f"[decker] sense disambiguation unavailable ({error}); "
                    "keeping every sense",
                    file=sys.stderr,
                )
                self._warned = True
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

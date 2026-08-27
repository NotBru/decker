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

PROMPT = """\
You are helping build language-learning cards from a text in {language}.

Sentence: {sentence}
Term as it appears: {surface}, marked ⟨like this⟩ in the sentence above.
Judge that occurrence only: the same word elsewhere in the sentence may well
be a different one.

Numbered senses of the Wiktionary page(s) {title}:
{senses}

Reply with the numbers of the senses this occurrence actually uses. Each sense
you keep becomes a flashcard of its own, so keep as few as truly apply --
usually exactly one. Keep more only where the occurrence genuinely carries more
than one meaning at once, not merely because a sense is nearby or related. If
none fit, keep the single closest one.
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
    ) -> tuple[Sense, ...]:
        """Return the senses worth glossing, in their original order.

        ``sources`` names the page each sense came from, so a term pooled
        from more than one spelling shows the model which entry is which.
        """
        if not self.enabled or len(senses) <= 1:
            return senses
        listing = "\n".join(
            f"{number}. {_labelled(sense, parts_of_speech, sources, number - 1)}"
            for number, sense in enumerate(senses, start=1)
        )
        prompt = PROMPT.format(
            language=language,
            sentence=sentence,
            surface=surface,
            title=title,
            senses=listing,
        )
        chosen = self._ask(prompt)
        if chosen is None:
            return senses
        kept = tuple(
            sense
            for number, sense in enumerate(senses, start=1)
            if number in chosen
        )
        return kept or senses

    def _ask(self, prompt: str) -> set[int] | None:
        try:
            response = self.client().chat(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                format=SCHEMA,
                options={"temperature": 0},
            )
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

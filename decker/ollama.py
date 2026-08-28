"""One local model, asked one short question at a time.

Both stages that need a model -- sense disambiguation, and translation when
the mother language is not the one the edition writes in -- talk to ollama the
same way: a prompt whose fixed instructions come first, an answer under a JSON
schema, the model's own reasoning turned off, and one warning for the whole
run when the host cannot be reached. That shape lives here; the prompts live
with the stage that writes them.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass

#: The model is parametrizable; this is the design's default, for every stage
#: that asks a model anything.
DEFAULT_MODEL = "gemma4"

#: Ollama has no authentication, so it is never exposed beyond a loopback or a
#: tunnel. The fallback is ollama's own default; a host reached through a
#: tunnel -- a forwarded GPU box, say -- is named by ``OLLAMA_HOST``.
DEFAULT_HOST = "http://localhost:11434"


@dataclass
class Session:
    """A model on an ollama host, and what to say when it is not there."""

    model: str = DEFAULT_MODEL
    host: str | None = None
    #: What the run goes without, named in the warning below, so a degraded
    #: run says which stage lost its model rather than only that one did.
    what: str = "the model"
    #: What happens instead, named in the same warning.
    fallback: str = ""

    def __post_init__(self) -> None:
        self._client = None
        self._warned = False
        self._thinkable = True

    def client(self):
        if self._client is None:
            import ollama

            host = self.host or os.environ.get("OLLAMA_HOST") or DEFAULT_HOST
            self._client = ollama.Client(host=host)
        return self._client

    def ask(self, prompt: str, schema: dict) -> dict | None:
        """The model's answer to one prompt, decoded, or ``None`` if it has none."""
        try:
            response = self._chat(prompt, schema)
            return json.loads(response["message"]["content"])
        except Exception as error:  # ollama down, model missing, bad JSON
            self.warn(str(error))
            return None

    def warn(self, reason: str) -> None:
        """Say once that the run is going without this model."""
        if self._warned:
            return
        tail = f"; {self.fallback}" if self.fallback else ""
        print(f"[decker] {self.what} unavailable ({reason}){tail}", file=sys.stderr)
        self._warned = True

    def _chat(self, prompt: str, schema: dict):
        """One call, with the model's own reasoning turned off if it has any.

        The answer is a few values under a schema, so a chain of thought buys
        nothing and costs the entire call: qwen3:1.7b spent 4222 thinking
        tokens and 80 seconds on a question it answers in 2.3 seconds without.
        A client that does not take the argument is asked again without it,
        and not asked with it again for the rest of the run.
        """
        arguments = dict(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            format=schema,
            options={"temperature": 0},
        )
        if self._thinkable:
            try:
                return self.client().chat(**arguments, think=False)
            except TypeError:
                self._thinkable = False
        return self.client().chat(**arguments)

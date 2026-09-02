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
#: that asks a model anything. It is measured rather than guessed: on the
#: eight etymologies that came back untranslated from a German run, this one
#: answers all eight once the translation schema requires the field, where
#: gemma3:4b echoes its English input back on three of them -- a well-formed
#: answer nothing downstream can catch. It pulls from the registry like any
#: other tag; what it costs is size -- 9.6 GB against gemma3:4b's 3.3 -- so a
#: host without the room degrades and says so, naming what it does hold.
DEFAULT_MODEL = "gemma4:latest"

#: Ollama has no authentication, so it is never exposed beyond a loopback or a
#: tunnel. The fallback is ollama's own default; a host reached through a
#: tunnel -- a forwarded GPU box, say -- is named by ``OLLAMA_HOST``.
DEFAULT_HOST = "http://localhost:11434"

#: A model can be named once for a whole shell, the way the host is. The two
#: have to agree, and rarely do by accident: a tunnelled GPU box and a laptop's
#: own ollama hold different tags, so a host named in the environment and a
#: model left to its default is exactly how a run ends up asking for something
#: that is not there.
MODEL_VARIABLE = "DECKER_MODEL"


def default_model() -> str:
    """The model a run uses when it is not told one."""
    return os.environ.get(MODEL_VARIABLE) or DEFAULT_MODEL


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
        self._warned = True
        tail = f"; {self.fallback}" if self.fallback else ""
        print(
            f"[decker] {self.what} unavailable ({reason}){self._held()}{tail}",
            file=sys.stderr,
        )

    def _held(self) -> str:
        """What the host does have, when it does not have what was asked for.

        A missing model otherwise comes back as its own name thrown back at
        the run, which reads the same whether the tag is misspelled, the host
        is the wrong one, or the model was simply never pulled there. Naming
        the tags the host holds tells those three apart in one line, and it is
        asked for once, on the way to a warning that was already going to be
        printed.
        """
        try:
            response = self.client().list()
        except Exception:  # the host is unreachable; the warning says so
            return ""
        entries = getattr(response, "models", None)
        if entries is None and isinstance(response, dict):
            entries = response.get("models", ())
        names = []
        for entry in entries or ():
            #: ollama's client has returned both objects and plain dicts.
            name = getattr(entry, "model", None)
            if name is None and isinstance(entry, dict):
                name = entry.get("model") or entry.get("name")
            if name:
                names.append(str(name))
        if not names:
            return ""
        return f"; the host holds {', '.join(sorted(names))}"

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

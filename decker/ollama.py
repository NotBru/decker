"""One local model, asked one short question at a time.

Both stages that need a model -- sense disambiguation, and translation when
the mother language is not the one the edition writes in -- talk to ollama the
same way: a prompt whose fixed instructions come first, an answer under a JSON
schema, the model's own reasoning turned off, and one warning for the whole
run when the host cannot be reached. That shape lives here; the prompts live
with the stage that writes them.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path

#: The model is parametrizable; this is the design's default, for every stage
#: that asks a model anything, and it is measured rather than guessed.
#:
#: The criterion, settled 2026-09-15 with Bru's ceiling: a deck may be slow but
#: not much slower than ten seconds a card, and *within* that ceiling the scarce
#: resource is not the wall clock, it is the learner. A run makes about one call
#: per card, so anything up to a couple of seconds a call is free; what is not
#: free is a card the learner did not need. So the default is the model that
#: teaches the same text in the fewest cards while answering the same questions
#: correctly. Four models, all of them inside the ceiling, all of them scoring
#: 8/9 on the nine known-answer checks over the same five Spanish sentences:
#:
#:     model            glosses  Hebrew prefix cards  gendered rules  s/call
#:     gemma4:latest         41         11 (8 right)               0     1.4
#:     qwen3.5:4b            47         19 (15 right)              0     0.4
#:     qwen3:14b             60         17 (9 right)               3     2.6
#:     gemma3:4b            110         48 (43 right)              2     0.6
#:
#: `gemma4:latest` wins every column that is about the deck and loses only the
#: one that stopped mattering. It is also the only model measured on the
#: translation side -- eight German etymologies answered where `gemma3:4b`
#: echoed its English back on three.
#:
#: What it gives up is the laptop: 9.6 GB against 3.3, so a run with no tunnel
#: cannot have it. `model-backends.md` has already recorded that the laptop is
#: not where a deck gets built -- it is for verifying a handful of sentences --
#: and `--model qwen3.5:4b` or $DECKER_MODEL is one flag for the runs where
#: that is wrong.
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


def _said_something(response) -> bool:
    """Whether a reply carries an answer at all, whatever shape it arrives in.

    ollama's client has returned both objects and plain dicts, and the content
    is the only field `ask` reads.
    """
    message = getattr(response, "message", None)
    if message is None and isinstance(response, dict):
        message = response.get("message")
    content = getattr(message, "content", None)
    if content is None and isinstance(message, dict):
        content = message.get("content")
    return bool(content and content.strip())


@dataclass
class Session:
    """A model on an ollama host, and what to say when it is not there."""

    model: str = DEFAULT_MODEL
    host: str | None = None
    #: Ask again even when the answer is already on disk.
    refresh: bool = False
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
        """The model's answer to one prompt, decoded, or ``None`` if it has none.

        Answers are kept on disk between runs. Both stages send a prompt that
        is a pure function of what they are asking about, at temperature zero,
        so the answer is a pure function of the request: the same model asked
        the same thing under the same schema has already said what it is going
        to say. Nothing else in a run is recomputed -- pages, titles and
        recordings are all cached -- so before this, a second run of the same
        text repeated the whole of its cost and none of its work.
        """
        path = self._remembered(prompt, schema)
        if path is not None and not self.refresh and path.exists():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                pass  # a half-written or unreadable answer is simply asked again
        try:
            response = self._chat(prompt, schema)
            answer = json.loads(response["message"]["content"])
        except Exception as error:  # ollama down, model missing, bad JSON
            self.warn(str(error))
            return None
        if path is not None:
            self._remember(path, answer)
        return answer

    def _remembered(self, prompt: str, schema: dict) -> "Path | None":
        """Where this exact question's answer is kept, if anywhere.

        The model is part of the key because two models answer differently,
        and the schema is because it decides the shape of the answer. The
        prompt carries everything else, so editing a prompt in the source
        invalidates its answers without anyone having to remember to.
        """
        try:
            from decker.wiktionary import cache_dir
        except Exception:
            return None
        question = json.dumps(
            [self.model, schema, prompt], sort_keys=True, ensure_ascii=False
        )
        digest = hashlib.sha256(question.encode("utf-8")).hexdigest()[:32]
        return cache_dir() / "answers" / f"{digest}.json"

    @staticmethod
    def _remember(path: "Path", answer: object) -> None:
        """Keep an answer, or carry on without keeping it."""
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            #: Written beside and moved into place, so a run interrupted
            #: mid-write leaves no half-answer for the next one to read.
            temporary = path.with_suffix(".part")
            temporary.write_text(
                json.dumps(answer, ensure_ascii=False), encoding="utf-8"
            )
            temporary.replace(path)
        except OSError:
            pass

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

        Two ways a model can refuse that, and both end the same way -- once per
        run, and thinking stays on for the rest of it. A client that does not
        take the argument raises `TypeError`. A model can also take it and then
        answer *nothing*: `gpt-oss:20b` comes back with an empty content and an
        empty thinking, every time, and answers perfectly with the argument
        left off. Without this that reads as a broken schema and the stage
        degrades -- a run of a reasoning model kept every sense and wrote no
        rules, for no reason a warning could explain.
        """
        arguments = dict(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            format=schema,
            options={"temperature": 0},
        )
        if self._thinkable:
            try:
                response = self.client().chat(**arguments, think=False)
            except TypeError:
                self._thinkable = False
            else:
                if _said_something(response):
                    return response
                self._thinkable = False
                print(
                    f"[decker] {self.model} answers nothing with its reasoning "
                    "turned off; leaving it on for this run, which is slower",
                    file=sys.stderr,
                )
        return self.client().chat(**arguments)

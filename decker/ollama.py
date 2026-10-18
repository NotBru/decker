"""One model, asked one short question at a time.

Every stage that needs a model -- sense disambiguation, rules, unknown words,
and translation when the mother language is not the one the edition writes in
-- asks it the same way: a prompt whose fixed instructions come first, an
answer under a JSON schema, the model's own reasoning turned off, and the
run stopped when it cannot be had -- never a deck built without it. That shape lives here; the
prompts live with the stage that writes them.

The model is served by a backend: ollama, the default and the only one that
keeps the text on hardware Bru owns, or Anthropic's API when a run names it.
A backend is how a call is sent and what to list when it fails; everything
else -- the answer cache, the waiting, the warning -- is shared. See
docs/execution/model-backends.md.
"""

from __future__ import annotations

import hashlib
import threading
import json
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import NoReturn

from decker.console import DETAIL, console, count, log
from decker.reach import BLIPS, Gate

#: The model is parametrizable; this is the design's default, for every stage
#: that asks a model anything, and it is measured rather than guessed.
#:
#: The criterion is Bru's ceiling: a deck may be slow but not much slower than
#: ten seconds a card, and *inside* that ceiling the scarce resource is not the
#: clock, it is the learner. So the default is the model that answers the most
#: questions right and hands the learner the fewest cards for doing it.
#:
#: Measured cold -- every answer re-asked -- on the 160-sentence, ten-language
#: benchmark in `tools/benchmark/`, half Wikipedia and half written to split
#: the models, on fesat's GTX 2060, 2026-10-11:
#:
#:     model            passed   glosses   cold wall
#:     qwen3:14b       153/211     1,751      6,929s
#:     qwen3.5:latest  147/211     1,728      5,161s
#:     gemma4:latest   144/211     1,672      1,648s
#:     qwen3.5:4b      116/211     1,722      1,634s
#:     gemma3:4b        91/211     1,949      1,444s
#:
#: `gemma4:latest` answers 28 more questions than `qwen3.5:4b` in the same wall
#: clock and with the fewest glosses of any; the two bigger models are within
#: noise of it at three and four times the time. It costs the laptop: 9.6 GB on
#: disk against 3.3, so a CPU-only run in the container names `--model
#: qwen3.5:4b`.
#:
#: This is the third change. gemma4 was the default on a five-sentence
#: benchmark where every model scored alike; `qwen3.5:4b` replaced it on 24
#: checks where it led by one; 211 checks reversed that by 28. Each benchmark
#: that could tell the models apart better undid the last choice, which is the
#: point of building them.
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

#: Who serves the model. Named in its own right, never read off the model's
#: name: the same name can be served by several providers, and `--ollama-host`
#: keeps meaning ollama and nothing else. ollama is the default because it is
#: the one that sends no sentence anywhere; a hosted backend is used only by a
#: run that asks for it.
BACKENDS = ("ollama", "anthropic")
BACKEND_VARIABLE = "DECKER_BACKEND"

#: Set from `--backend`, the way `pages.HOST` is set from `--wiktionary-host`;
#: the environment is read when it is not.
BACKEND: str | None = None

#: Each backend's default, since a tag one serves is a name the other has
#: never heard of. Claude Haiku 5.5 is Anthropic's cheapest tier, at $0.10 per
#: million input tokens: a run is on the order of a million, so a dime.
DEFAULT_MODELS = {"ollama": DEFAULT_MODEL, "anthropic": "claude-haiku-5-5"}

#: Dollars per million tokens in and out, for the hosted models whose price
#: is known, so a run can say what it cost. Haiku 5.5's holds for prompts up to
#: 100K tokens, which every prompt decker writes is.
PRICES = {"claude-haiku-5-5": (0.10, 0.50)}


def current_backend() -> str:
    """The backend a run uses when it is not told one."""
    return BACKEND or os.environ.get(BACKEND_VARIABLE) or "ollama"


def default_model() -> str:
    """The model a run uses when it is not told one."""
    return os.environ.get(MODEL_VARIABLE) or DEFAULT_MODELS[current_backend()]


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


#: The questions being asked right now, by digest, and the lock that guards
#: the register. Two threads want the same answer often enough to matter:
#: the prefetcher reads ahead of the gloss loop, and where it is only a little
#: ahead the loop arrives at a question the prefetcher has already sent. The
#: cache cannot dedupe those -- it is a file that does not exist yet -- so the
#: second asker waits for the first instead of paying the GPU twice.
_IN_FLIGHT: dict[str, threading.Event] = {}
_IN_FLIGHT_LOCK = threading.Lock()

#: How long a waiter waits before deciding the other asker is not coming back.
#: Longer than any answer takes and shorter than a hung run: on a miss the
#: question is simply asked again, which is what would have happened anyway.
IN_FLIGHT_TIMEOUT = 120.0

#: One gate per host, shared by every stage that asks it: disambiguation,
#: rules, translation and the unknown-word questions all hold on the same
#: outage and it is logged once, not once a stage.
_GATES: dict[str, Gate] = {}
_GATES_LOCK = threading.Lock()


def _gate(host: str, named: bool = True) -> Gate:
    with _GATES_LOCK:
        if host not in _GATES:
            def probe(host: str = host) -> bool:
                import ollama

                ollama.Client(host=host, timeout=10).list()
                return True

            #: A default nobody named is most often a shell that forgot
            #: OLLAMA_HOST, so its wait says how to name the right one.
            name = f"ollama at {host}" + (
                "" if named else " (the default: name another with --ollama-host or OLLAMA_HOST)"
            )
            _GATES[host] = Gate(name, probe)
        return _GATES[host]


def _anthropic_gate() -> Gate:
    with _GATES_LOCK:
        if "anthropic" not in _GATES:
            def probe() -> bool:
                import anthropic

                anthropic.Anthropic(timeout=10, max_retries=0).models.list(limit=1)
                return True

            _GATES["anthropic"] = Gate("the Anthropic API", probe)
        return _GATES["anthropic"]


def _unreachable(error: BaseException) -> bool:
    """Whether a failed call never reached a model that could answer it.

    ollama's client turns a refused connection into the builtin
    `ConnectionError`; a reset, a hang-up mid-answer or a timeout arrive as
    httpx's own transport errors. Anthropic's are its connection errors, and
    the 5xx and 429 it still returns once the client's own retries are spent:
    an overloaded API will answer later, the way a dropped tunnel will.
    Anything else -- a 404 for a model the host does not hold, a missing key,
    a reply that is not JSON -- was an answer, however useless.
    """
    if isinstance(error, (ConnectionError, TimeoutError)):
        return True
    try:
        import anthropic
    except ImportError:
        pass
    else:
        if isinstance(error, (anthropic.APIConnectionError,
                              anthropic.InternalServerError,
                              anthropic.RateLimitError)):
            return True
    try:
        import httpx
    except ImportError:
        return False
    return isinstance(error, httpx.TransportError)


def spending() -> str | None:
    """What this run spent on a metered backend, in a line, if anything."""
    stats = console.stats
    tokens_in, tokens_out = stats["tokens.in"], stats["tokens.out"]
    if not tokens_in:
        return None
    line = f"{tokens_in:,} tokens in, {tokens_out:,} out"
    models = {name.removeprefix("tokens.model.") for name in stats.counts
              if name.startswith("tokens.model.") and stats[name]}
    if len(models) == 1 and (price := PRICES.get(next(iter(models)))):
        line += f", ${(tokens_in * price[0] + tokens_out * price[1]) / 1e6:.2f}"
    return line


def _closed(schema: object) -> object:
    """A schema with every object closed, which Anthropic's decoder requires.

    The stages write one plain schema for every backend; ollama takes it as it
    is, and this is the whole of the adaptation the other one needs.
    """
    if isinstance(schema, dict):
        closed = {key: _closed(value) for key, value in schema.items()}
        if closed.get("type") == "object":
            closed.setdefault("additionalProperties", False)
        return closed
    if isinstance(schema, list):
        return [_closed(value) for value in schema]
    return schema


#: How many times a question whose answer could not be read is asked again
#: before the run stops. With no temperature to pin it, a hosted model can
#: answer the same question differently, so a bent answer is worth a retry.
ANSWER_TRIES = 3


class Unavailable(RuntimeError):
    """The model could not be had, and the run stops rather than go without.

    Before 2026-10-18 each stage had a fallback -- every sense kept, every
    inflected form its own card, the cards left in English -- and said so in
    one line. A run with a missing key finished with 85 glosses where the model
    gives 19 and exited 0. Bru's rule since: no degraded runs, at any cost; if
    something is missing, the run fails. The answers already given are cached,
    so running again costs only what was not yet asked.
    """


def _reason(error: BaseException) -> str:
    return str(error) or type(error).__name__


@dataclass
class Session:
    """A model on a backend, and what to say when it is not there."""

    model: str = DEFAULT_MODEL
    #: The ollama host; the other backends have no use for one.
    host: str | None = None
    #: Ask again even when the answer is already on disk.
    refresh: bool = False
    #: The stage asking, named when the run stops, so it says which stage
    #: lost its model rather than only that one did.
    what: str = "the model"

    #: Which backend serves `model`; the run's, unless a caller says otherwise.
    backend: str = field(default_factory=current_backend)

    def __post_init__(self) -> None:
        self._client = None
        self._thinkable = True

    def _host(self) -> str:
        return self.host or os.environ.get("OLLAMA_HOST") or DEFAULT_HOST

    def _named(self) -> bool:
        """Whether the run was told which host to use, rather than defaulting."""
        return bool(self.host or os.environ.get("OLLAMA_HOST"))

    def client(self):
        if self._client is None:
            if self.backend == "anthropic":
                import anthropic

                #: More retries than the client's two: a run is thousands of
                #: calls, and an overloaded API is backed off from here before
                #: it is waited out at the gate.
                self._client = anthropic.Anthropic(max_retries=8)
            else:
                import ollama

                self._client = ollama.Client(host=self._host())
        return self._client

    def _gate(self) -> Gate:
        if self.backend == "anthropic":
            return _anthropic_gate()
        return _gate(self._host(), self._named())

    def ask(self, prompt: str, schema: dict) -> dict:
        """The model's answer to one prompt, decoded; `Unavailable` if it has none.

        Answers are kept on disk between runs. Both stages send a prompt that
        is a pure function of what they are asking about, at temperature zero,
        so the answer is a pure function of the request: the same model asked
        the same thing under the same schema has already said what it is going
        to say. Nothing else in a run is recomputed -- pages, titles and
        recordings are all cached -- so before this, a second run of the same
        text repeated the whole of its cost and none of its work.
        """
        path = self._remembered(prompt, schema)
        remembered = self._recall(path)
        if remembered is not None:
            return remembered
        #: Nobody has this answer yet. Whoever registers the question asks it;
        #: anybody else waits for that one and reads what it wrote.
        waiting = None
        if path is not None and not self.refresh:
            with _IN_FLIGHT_LOCK:
                waiting = _IN_FLIGHT.get(path.name)
                if waiting is None:
                    _IN_FLIGHT[path.name] = threading.Event()
        if waiting is not None:
            waiting.wait(IN_FLIGHT_TIMEOUT)
            remembered = self._recall(path)
            if remembered is not None:
                return remembered
        #: Timed, because this is where a run's wall clock goes and the whole
        #: of the model comparison in `DEFAULT_MODEL` is these seconds added
        #: up. At `-vv` a slow model is visible in the first minute rather
        #: than at the end of the run.
        started = time.monotonic()
        count("model.asked")
        blips = 0
        tries = 0
        while True:
            try:
                answer = json.loads(self._answer(prompt, schema))
                if not isinstance(answer, dict):
                    raise ValueError(f"{self.model} answered {answer!r}, not an object")
                break
            except Exception as error:  # backend down, model missing, bad JSON
                #: Unreachable is not an answer: whichever host the run uses,
                #: named or the default, is waited for and the question asked
                #: again, so a dropped tunnel or a forgotten OLLAMA_HOST costs
                #: time and never a sense. There is no run without a model.
                if _unreachable(error) and blips < BLIPS:
                    if not self._gate().wait(_reason(error)):
                        blips += 1
                    started = time.monotonic()
                    continue
                tries += 1
                if isinstance(error, ValueError) and tries < ANSWER_TRIES:
                    log(f"[decker] {self.what}: {self.model} gave an answer that "
                        f"could not be read ({_reason(error)}); asking again",
                        kind="warn")
                    continue
                self._released(path)
                self.fail(_reason(error))
        #: Added up rather than only printed: the difference between a cold run
        #: and a warm one is the whole difference in wall clock, and a total on
        #: the screen says which this is without waiting for the run to end.
        console.stats.spent("model", time.monotonic() - started)
        log(f"[decker]     {self.what}: {self.model} answered in "
            f"{time.monotonic() - started:.1f}s", level=DETAIL, kind="detail")
        if path is not None:
            self._remember(path, answer)
            self._released(path)
        return answer

    def _recall(self, path: "Path | None") -> dict | None:
        """The answer already on disk, or ``None``."""
        if path is None or self.refresh or not path.exists():
            return None
        try:
            answer = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None  # a half-written or unreadable answer is asked again
        log(f"[decker]     {self.what}: remembered", level=DETAIL, kind="detail")
        count("model.remembered")
        return answer

    @staticmethod
    def _released(path: "Path | None") -> None:
        """Let go of a question, waking whoever waited for its answer."""
        if path is None:
            return
        with _IN_FLIGHT_LOCK:
            waiting = _IN_FLIGHT.pop(path.name, None)
        if waiting is not None:
            waiting.set()

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
            temporary = path.with_suffix(f".{os.getpid()}.{threading.get_ident()}.part")
            temporary.write_text(
                json.dumps(answer, ensure_ascii=False), encoding="utf-8"
            )
            temporary.replace(path)
        except OSError:
            pass

    def fail(self, reason: str) -> "NoReturn":
        """Stop the run: this stage cannot have its model."""
        count("model.failed")
        #: The backend is named because "unavailable" reads the same whether a
        #: tunnel is down, a key is missing or a tag was never pulled, and
        #: those are three different fixes.
        raise Unavailable(
            f"{self.what}: {self.model} unavailable from {self.backend} "
            f"({reason}){self._held()}"
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
        if self.backend == "anthropic":
            try:
                names = [model.id for model in self.client().models.list()]
            except Exception:  # no key, or no network; the warning says which
                return ""
            return f"; the API serves {', '.join(sorted(names))}" if names else ""
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

    def _answer(self, prompt: str, schema: dict) -> str:
        """The text of one answer, from whichever backend serves the model."""
        if self.backend == "anthropic":
            return self._message(prompt, schema)
        response = self._chat(prompt, schema)
        return response["message"]["content"]

    def _message(self, prompt: str, schema: dict) -> str:
        """One call to Anthropic's API, thinking off where the model allows it.

        The same reasoning as `_chat`'s, and the same once-per-run retreat:
        Haiku 5.5 takes thinking disabled at its default effort, but the
        current Opus and Sonnet refuse it outright, and there the next best
        thing is thinking left to the model at the lowest effort. No
        temperature is sent, since the current models reject any but their
        own; the answer cache is what keeps a second run's answers the first
        one's.
        """
        import anthropic

        arguments = dict(
            model=self.model,
            #: An answer is a few values, a translation a paragraph; this is
            #: room for those and for thinking on the models that insist.
            max_tokens=4096,
            messages=[{"role": "user", "content": prompt}],
        )
        shape = {"type": "json_schema", "schema": _closed(schema)}
        response = None
        if self._thinkable:
            try:
                response = self.client().messages.create(
                    **arguments,
                    thinking={"type": "disabled"},
                    output_config={"format": shape},
                )
            except anthropic.BadRequestError as error:
                if "thinking" not in str(error):
                    raise
                self._thinkable = False
                log(
                    f"[decker] {self.model} will not answer with its reasoning "
                    "turned off; leaving it on at low effort for this run",
                    kind="warn",
                )
        if response is None:
            response = self.client().messages.create(
                **arguments, output_config={"format": shape, "effort": "low"}
            )
        #: Tallied because a hosted backend is metered: the run's last line
        #: says what it spent.
        count("tokens.in", response.usage.input_tokens)
        count("tokens.out", response.usage.output_tokens)
        count(f"tokens.model.{self.model}", 1)
        if response.stop_reason == "refusal":
            raise ValueError(f"{self.model} declined to answer")
        return "".join(block.text for block in response.content if block.type == "text")

    def _chat(self, prompt: str, schema: dict):
        """One call to ollama, with the model's own reasoning turned off if it has any.

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
                log(
                    f"[decker] {self.model} answers nothing with its reasoning "
                    "turned off; leaving it on for this run, which is slower",
                    kind="warn",
                )
        return self.client().chat(**arguments)

# Model backends: ollama, OpenAI-compatible, Anthropic

Written by an AI agent, not by hand. It records the choices taken while making the model a
pluggable thing rather than an ollama thing. [The v1 design](../instructions/v1/design.md) remains
the source of truth: where this contradicts it, the design wins and the code is wrong.

The design says the stages that need a model are served "by a local model served by ollama", and
until now that was the whole story. It is being widened to three backends on Bru's instruction —
**ollama, an OpenAI-compatible endpoint, and Anthropic** — with the design line to be rewritten by
hand to match. Decker is not married to ollama; it is married to *one short question at a time,
answered under a schema*, and that is a smaller commitment than a vendor.

## Why this is worth doing

- **The GPU box is a single point of failure.** Sense disambiguation, translation and now
  morphological rules all stop when `ssh -N fesat` stops. On 2026-09-12 the box was simply off and
  Bru was away from it, and a run that degrades to "keep every sense" is not a run.

- **The laptop is not a fallback.** CPU-only inference in the devcontainer is what the GPU box was
  introduced to avoid: sustained all-core load on a machine that powers off under it. It remains
  available, capped, for verification on a handful of sentences — it is not where a deck gets built.

- **Cost per run decides how freely a stage can be tuned.** This is the argument that moved it. A
  full run is on the order of 10⁶ input tokens, so the gap between a $1.00/1M model and a $0.10/1M
  one is the gap between re-running the text while iterating and rationing test runs. A stage like
  morphological rules, which is two model calls per new form-of word and wants its prompts tuned
  against real output, is exactly the stage that cannot afford to be metered. Backends are what let
  the cheap tier be used for iteration and a better model for a final build, without the pipeline
  knowing which is which.

## The seam

`decker/ollama.py`'s `Session` is already the entire interface both existing stages use:

```
Session.ask(prompt: str, schema: dict) -> dict | None
```

A prompt in, a JSON object under a schema out, `None` when the model cannot be reached, temperature
zero, and one warning per run. Everything vendor-specific lives in two methods — `_chat`, which
sends the call, and `_held`, which lists what the host has when the ask fails. So a backend is those
two methods, and the rest of the file — the disk cache, the warning discipline, the fallback when a
client rejects an argument — is shared by all three.

Three consequences worth writing down:

- **The answer cache already keys on the model.** `_remembered` hashes `[model, schema, prompt]`, so
  answers from different backends cannot collide and switching backends re-asks nothing that was
  asked of the *same* model. Moving from the GPU box to a hosted model and back costs nothing and
  invalidates nothing. This was not built for backends; it falls out of the model being in the key
  because two models answer differently.

- **Schemas need a small adaptation per backend, not per stage.** ollama takes a bare JSON Schema as
  `format=`; the OpenAI-compatible shape is `response_format: {type: "json_schema", ...}` and wants
  `additionalProperties: false`; Anthropic's is `output_config: {format: ...}`. The stages keep
  writing one plain schema (`disambiguation.SCHEMA` and friends) and the backend wraps it. A stage
  that had to know which backend it was talking to would defeat the point.

- **Thinking is off everywhere, by different means.** `_chat` passes `think=False` to ollama and
  remembers when a client rejects it. Hosted small models either have no thinking or take a
  parameter to disable it; whichever it is belongs in the backend, because the reason is the same
  everywhere and was measured once: qwen3:1.7b spent 4222 reasoning tokens and 80 seconds on a
  question it answers in 2.3 seconds without.

## Naming a backend

The host and the model are already the pair that has to agree, and `$OLLAMA_HOST` with
`$DECKER_MODEL` is how a run ends up asking the wrong host for something that is not there. A third
thing to get wrong makes that worse, so:

- `--ollama-host` keeps meaning ollama and nothing else. It does not become a generic base URL that
  silently changes which vendor is being talked to.
- The backend is named in its own right, and the model name is not asked to imply it. A model string
  is not a reliable discriminator — the same name is served by several providers at different
  prices.
- When a backend cannot be reached, the warning says which backend, the way `_held` already names
  the tags an ollama host holds. "The model is unavailable" reads identically whether a tunnel is
  down, a key is missing or a tag was never pulled, and those are three different fixes.

## What this costs in privacy, stated plainly

[A local Wiktionary](local-wiktionary.md) exists in large part because "the model runs on hardware
Bru owns precisely so the text never leaves it" — page fetches were the gap in that, and the mirror
closed it. A hosted backend reopens it from the other side: the prompts carry sentences of the
source verbatim, marked at the occurrence, along with the senses under consideration.

Bru has weighed this and accepted it (2026-09-12) for the hosted backends. It is recorded here
rather than left implicit because the mirror's rationale would otherwise read as describing a
property the system no longer has. Two things follow that are not matters of taste:

- **The ollama backend keeps the original property** and stays the default. A run that never names a
  hosted backend never sends a sentence anywhere.
- **A free tier is not the same as a paid one.** Providers that offer a free quota generally reserve
  the right to train on what is sent to it, and the paid tier is what buys that out. For a source
  text that is deliberately kept out of git, that distinction is worth the tenth of a cent.

## Models, measured

The benchmark that matters is the five-sentence, nine-known-answer one described in
`definition-fetching.md`, scored on check passes *and* gloss count — a model that keeps every sense
passes the recall checks for free, so the count is the honest signal.

| model | where | checks | glosses | wall |
|---|---|---|---|---|
| gemma4 | GTX2060, tunnel | 9/9 | 28 | 49s |
| gemma3:4b | laptop CPU | 8/9 | 34 | 208s |
| qwen3:1.7b | laptop CPU | 7/9 | 84 | 132s |

qwen3:1.7b is the cautionary row: it barely discriminates, and every extra kept sense is another
gloss and another call, so it is slower overall despite being faster per call.

### qwen3.5:4b, and why it is now the default

Measured 2026-09-13 on a shorter input — four sentences, laptop CPU, same cached pages for both
models, on AC, and the output was byte-identical across two `--refresh-answers` runs, so these
counts are not a sample of one:

| model | where | glosses | wall | duplicate senses kept |
|---|---|---|---|---|
| qwen3.5:4b | laptop CPU | 40 | 202s | none |
| gemma3:4b | laptop CPU | 49 | 162s | tío, lo, viejo, de, carga, solo ×2, bueno, decir |

(Those totals include the concept cards — eleven and twelve respectively, so 29 word glosses against
37.) The nine extra glosses are duplicates, not recall — `carga` as both *load* and *cargo*,
`viejo` for an object and for a person, `tío` as the Spain-colloquial *dude* in a sentence about an
uncle. That is the qwen3:1.7b failure in milder form, and every kept sense is another card to study.
qwen3.5:4b also passes the case the old benchmark's ninth check was about: the same form twice in
one sentence, read two different ways.

Both models miss one case, `un decir` — the noun *saying*, answered with a verb sense. It is not a
part-of-speech filter narrowing the list before the model sees it: `disambiguation.py` has none, and
the page offers Noun/*saying* among its eleven senses. The models simply choose wrong.

It costs ~25% more wall time than gemma3:4b for fewer glosses, so it is slower per call. It is not
measured on the translation evidence that put `gemma4:latest` here before it — see
`definition-fetching.md` for what that trade is.

Local runs are capped — `OMP_NUM_THREADS=8` and `OLLAMA_NUM_THREAD=8` against 16 cores — because
Stanza builds its pipeline with no thread limit and torch will otherwise take all of them alongside
inference. The cap is about the machine staying up, not about speed.

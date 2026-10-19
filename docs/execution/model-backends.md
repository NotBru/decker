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

A prompt in, a JSON object under a schema out, and the run stopped (`Unavailable`, exit 2) when the
model cannot be had — since 2026-10-18; before, `None` and one warning per run, and the stage's
fallback. Everything vendor-specific lives in two methods — `_chat`, which
sends the call, and `_held`, which lists what the host has when the ask fails. So a backend is those
two methods, and the rest of the file — the disk cache, the stop, the retreat when a
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

- **Thinking is off everywhere, by different means — and some models refuse.** `_chat` passes
  `think=False` to ollama and remembers when a client rejects it. It also remembers when a *model*
  takes the argument and then answers nothing: `gpt-oss:20b` returns an empty content and an empty
  thinking on every call made that way, and answers perfectly with the argument left off. Read as a
  broken schema, which is what it looked like before 2026-09-15, that is a whole run degraded for no
  reason a warning could explain — every sense kept, no rules written. An empty answer to a
  `think=False` call now costs one retry with thinking on, one line on stderr, and nothing else for
  the rest of the run. Hosted small models either have no thinking or take a
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

## The Anthropic backend, as built (2026-10-18)

The first hosted backend; the OpenAI-compatible one came a day later, as OpenRouter, below. What
was decided while building it:

- **`--backend anthropic`, or `DECKER_BACKEND=anthropic`.** Its own flag, per the section above;
  `--ollama-host` is ignored by it. `pages.HOST`'s pattern: the CLI sets `ollama.BACKEND`, and a
  `Session` built anywhere — the four stages, the benchmark — reads it, so no stage learned a new
  argument.
- **The default model follows the backend.** `--model` no longer has a parse-time default:
  `$DECKER_MODEL` if set, else `gemma4:latest` on ollama and **`claude-haiku-5-5`** on Anthropic —
  the cheapest tier (on 2026-10-18, $0.10 / $0.50 per million tokens, so a run was about a dime).
  A `$DECKER_MODEL` left over from ollama is a 404, and the warning lists what the API serves, which
  is the same answer `_held` gives for an untagged ollama model.
- **The schema is closed, nothing else.** `_closed` adds `additionalProperties: false` to every
  object, which Anthropic's decoder requires and ollama does not care about; it goes in as
  `output_config.format`.
- **Thinking off, with a retreat.** Haiku 5.5 takes `thinking: disabled` at its default effort. The
  current Opus and Sonnet reject it, and a 400 that names thinking switches the run, once, to
  thinking left on at `effort: low` — the same once-per-run shape as `gpt-oss:20b`'s on ollama.
- **No temperature.** The current models reject anything but their own sampling, so answers are not
  deterministic the way ollama's are at zero. The answer cache is what keeps a second run's answers
  the first one's; `--refresh-answers` on this backend can change a deck.
- **What is waited out.** Connection errors, and the 5xx/429 left once the client's own eight retries
  are spent, go to a gate named "the Anthropic API", probed by listing one model. A missing or wrong
  key, a refusal, or an unknown model is an answer: the run stops, naming the backend, the model and
  — for an unknown model — what the API does serve.

- **Tokens, never dollars.** A run on a metered backend ends with what it spent in tokens, finished
  or stopped. For a few hours it also printed dollars from a table of prices in the code; Bru struck
  it the same day — a price list in the code, or one kept by hand, goes stale without a word, and the
  bill is the provider's to report. The dollar figures below were worked out by hand from that day's
  price page and are dated with it.

### Haiku 5.5 on Gokurakugai 0001, against gemma4, 2026-10-18

The first real run: the whole volume, `--target-lang ja --teach-script`, the flags `decks/japanese.apkg`
was built with on `gemma4:latest`, with the Japanese rule book set aside so Haiku wrote its own.

| | gemma4 (tunnel) | Haiku 5.5 |
|---|---|---|
| glosses / cards | 1,524 / 2,986 | 1,611 / 3,171 |
| rules written | 0 (22 reused) | 26 |
| wall clock | — | ~20 min |
| cost | the GPU box's power | 2,132,114 tokens in, 28,242 out: **$0.23** |

1,296 glosses are the same in both. Of the 298 terms whose senses differ, about thirty were read
against their speech bubbles, and neither model wins:

- **Haiku is right where gemma4 is not** mostly where gemma4 floods a page with everything on it:
  `くだ` (a truncated *ください*) gets nine senses of 管 from gemma4 and one from Haiku; `れん`,
  `ぼ`, `こっ`, `世の中` and `心` likewise. Haiku also reads idiom better: `ハイハイ` is *yeah, sure*,
  not a baby crawling; `やった` in `自分でやったんじゃん` is the past of やる, not *hurrah*; `病気だろ`
  is the slang *you're sick in the head*.
- **gemma4 is right where Haiku is not** where Haiku keeps senses no reading supports — `こん`
  (from the OCR-garbled `探してこんだ`) gets fourteen, `着` in `服着てん` seven — and where it picks
  the provocative sense: `暇` as *divorce*, `春` as *sex*, and `アル` (the name アルマ) as an ethnic
  slur. `またまた` is *come off it*, which gemma4 has and Haiku reads as *again and again*.
- **Both are wrong** where the pipeline is: `ちゃう` in `誘拐されちゃう` is the contraction of
  *てしまう*, which neither sense on the page says, and OCR noise (`午短短短知短う`) is glossed by
  both.

**Page 1 through the larger Claude models, 2026-10-18.** Five bubbles, `--no-rules`, after the
passage went to one bubble a line. Sonnet 5.5, Opus 5.5 and Fable 5.1 all reject thinking turned
off and ran at low effort; all three read `出て` as *to answer (the phone or door)*, where Haiku and
gemma4 read *to leave a place*. They also read `よお` as a stretched `よ`, not `よう`; and `へ` as
*to, towards*, not *a fart* (which is still wrong: `へいへいー` is cut into `へい · へ · いー`, an
extraction problem). Opus and Fable read `１話` as a counter for stories, not TV episodes. Cost of
the page: Haiku $0.002, Sonnet $0.06, Opus $0.12, Fable $0.31 — scaled by Haiku's 2.1M tokens for the
volume, roughly $8, $15 and $40 a volume.

So on this text Haiku is a peer of gemma4, not an upgrade: about as many right answers, 6% more
glosses, and a habit of keeping the vulgar sense that a learner's deck should not. What it buys is
that it needs no GPU box, for a quarter of a dollar a volume. The 211-check benchmark is still the
way to rank it properly.

### Sonnet 5.5 on Gokurakugai 0001, against gemma4, 2026-10-19

The same flags as Haiku's run, thinking on at low effort (Sonnet refuses it off), and the answer
cache cold. **gemma4 was rebuilt for this on the same code**, both runs starting from an empty
Japanese rule book: `decks/japanese.apkg` as it stood had been built at 13:21 on 2026-10-18, before
that evening's commits — untitled words as terms, one bubble a line, multi-sense follow-ups,
no-spoiler explanations — so a comparison against it, Haiku's included, measured the code as much
as the model. The Sonnet deck is now `decks/japanese.apkg`, built with `--update` over the old one
so that an import corrects the cards in Anki.

| | gemma4 (tunnel) | Sonnet 5.5 |
|---|---|---|
| glosses / cards | 1,603 / 3,100 | 1,563 / 3,067 |
| rules written / carded | 19 / 2 | 20 / 0 |
| words with no entry read as a misspelling | 9 | 49 |
| wall clock | 23 min | 34 min |
| tokens | — | 2,394,384 in, 50,694 out |

1,286 glosses are shared. **Of the 160 terms whose senses differ, every one was read against the
bubbles it came from.** About a hundred are a draw: OCR noise (`午短短短知短う`, `研カレヤヤ`), the
one-kana fragments a component or a wrong cut leaves (`け`, `せ`, `ど`, `ふ`, `む`), two glosses that
say the same thing, names both explain, and particles used fifty times where both decks hold a
defensible sense. Of the rest:

- **Sonnet right, gemma4 wrong: 49.** Mostly the sense the bubble actually uses, where gemma4 took
  the first or the most concrete one: `出て(ください)` *answer the door*, `一文負けねえ` *won't knock
  a mon off*, `金蔓` *a cash cow* not *vine*, `５０じゃ済まねえ` *won't get off with*, `血を飲み`
  *drink* not *engulf*, `良かった` *thank goodness*, `表向き` *ostensibly*, `様に見える` *to seem*,
  `話長ェ` 長 *long* not *chief*, `いい加減` *enough already*, `対人` *versus*, `ハイハイ`, `やった`,
  `ヤヤ` as a name not an interjection, `描きに来ない` read *kaki* not *egaki*.
- **gemma4 right, Sonnet wrong: 9.** `またまたお嬢` *come off it* (Sonnet: *again and again*, as
  Haiku), `どうもありがとう`, `いや`, `が` as the case marker, `出回る` *to circulate*, `お前`'s `前`
  as the old honorific, `どの口が` *one's words*, `連れて`, and `ガッツあんな` — *you've got guts*,
  which Sonnet explains as a character called Guts.
- **Sonnet trims a flooded page**, as Haiku did: gemma4's three senses of `世の中` become one.

**Sonnet repairs some of Sudachi's cuts; gemma4 cards them.** A word with no entry is asked about,
and Sonnet reads five times as many of them as a misspelling of a word that has one — which is
what most of them are: `あっぶね`'s `ぶね` is *あぶない*, `わっかる`'s `かる` is *わかる*, `臭え` is
*臭い*, `みてえ` *みたい*, `ンな` *そんな*. gemma4 explains the fragment as it stands: `ぶね` *boat*,
`金取` *to take money*, `かる` *a filler sound*, `うさん` *suspicion*. Sonnet's readings are not all
right — `なー` as *なら*, `いー` as *い* — but it reaches some of the 19 cards counted in
[Term extraction](term-extraction.md) that no normalisation would.

**What a learner's deck should not carry.** `アル`, the short of アルマ in `アルは半禍の子なんだよ`, is
glossed as *the stereotypical sentence-final particle used by Chinese* — the kind of answer Haiku
gave on the same word. Three explanations — `タオ`, `アルマ`, `宝来` — say the name is "shown in
angle brackets": the ⟨⟩ that mark a term in the prompt leaked into card text, and `宝来`'s adds
"a place where a tab is run up", which is the story. gemma4 leaks neither, and calls アルマ "a name
of a thing".

So Sonnet is an upgrade on gemma4 where Haiku was a peer: about five right answers to every one
lost, among the differences that are not a draw, and a better reading of the words Sudachi broke. It
costs half an hour without the GPU box and the tokens above; the benchmark is still what would rank
it without resting on one reader.

## The OpenRouter backend, as built (2026-10-19)

The OpenAI-compatible backend, built for Bru's first paid DeepSeek run and pointed at OpenRouter
rather than at DeepSeek's own API: one key reaches every vendor, and the account came with a spend
limit set on the key itself. What was decided:

- **`--backend openrouter`, key in `OPENROUTER_API_KEY`.** Named for the service, not for the wire
  shape, because what it sends beyond the OpenAI fields — provider preferences, the reasoning
  switch — is OpenRouter's. Another OpenAI-compatible endpoint is `OPENROUTER_BASE` and those two
  fields away. The key is read from a file outside the repository (`~/.config/openrouter/key`, mode
  600) by the shell profile; it is never in the tree.
- **Default model `deepseek/deepseek-v4.1-flash`.** The first one asked through it.
- **No new dependency.** The call is one POST, made with `httpx`, which `anthropic` and `ollama`
  already bring; `pyproject.toml` is Bru's.
- **The schema as OpenAI's strict `json_schema`,** closed with the same `_closed` Anthropic needs.
  With `provider.require_parameters` the call is routed only to a provider that honours the schema
  and the reasoning switch; without it, OpenRouter may pick one that drops them silently, and the
  answer is whatever shape that provider felt like.
- **`provider.data_collection: deny`.** The sentences still leave the machine, but only to
  providers that say they do not keep prompts to train on. This narrows the routing; it does not
  make a hosted backend private.
- **Reasoning off with `reasoning: {enabled: false}`,** and the Anthropic backend's once-per-run
  retreat to low effort if a model's 400 names reasoning. DeepSeek V4.1 Flash takes it: a test
  call answered in 2 s with no reasoning tokens.
- **Busy is waited out.** A 429 or a 5xx — as a status, or as the `error` OpenRouter puts in a
  200's body when a provider fails mid-call — is a `ConnectionError` to the gate, like a dropped
  tunnel. A 402 (no credit), a bad key or an unknown model stops the run; an unknown model lists
  what OpenRouter serves from the same vendor.
- **Tokens, not dollars.** OpenRouter reports a `cost` per call; decker does not read it, for the
  reason `spending` gives — the console is where the bill is.

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

### qwen3.5:4b, and why it was the default until 2026-10-11

On 2026-10-11 the ten-language, 211-check benchmark put `gemma4:latest` 28 checks ahead of it at the
same wall clock, and the default moved back to gemma4 — see `benchmark.md` and the table in
`decker/ollama.py`. What follows is the measurement that made it the default.

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

### Four models over the two failures the survey found, 2026-09-14

A different question from the benchmark above, and the one
[the ten-language survey](language-survey.md) left open: are its two worst failures the model's or
the pipeline's? Same samples (Hebrew, Turkish and Hungarian, ~2,500 characters each), same cached
pages, one arm per fix, every run from an empty rule book. `qwen3.5:4b` and `qwen3:14b` were pulled
onto the GPU box for this; it already held the other two. Wall-clock times are not comparable —
`gemma4:latest` walked in with most of the survey's answers already in the answer cache — so the
tables carry counts, which are the same workload by construction.

**Hebrew: the seven clitic prefixes, as `cards / from the prefix's own entry / names of letters`,
with the run's total glosses beside them.** "Neither" is what the survey ran; "hint" is the
part-of-speech line alone; "title" is the bound-morpheme lookup alone; "both" is what ships. The
sample uses these seven 62 times in 333 term occurrences.

| model | size | neither | hint only | title only | both (ships) |
|---|---|---|---|---|---|
| `gemma4:latest` | 8B Q4_K_M | 9 / 0 / 7 (264 gl) | 12 / 0 / 6 (270 gl) | 12 / 9 / 3 (262 gl) | 11 / 8 / 3 (265 gl) |
| `qwen3.5:4b` | 4B Q4_K_M | 15 / 0 / 7 (281 gl) | 17 / 0 / 7 (272 gl) | 39 / 34 / 4 (302 gl) | 19 / 15 / 3 (271 gl) |
| `gemma3:4b` | 4B Q4_K_M | 12 / 0 / 7 (304 gl) | — | — | 48 / 43 / 3 (428 gl) |
| `qwen3:14b` | 14B Q4_K_M | 19 / 0 / 8 (283 gl) | — | — | 17 / 9 / 4 (274 gl) |

**Turkish and Hungarian: `rules written / rules stated over a gender the language does not have`**,
with no inventory paragraph, with the first wording of it, and with the wording that ships (the
first named *feminine nouns* in its own warning; see `morphological-rules.md`).

| model | Turkish: none / first wording / shipped | Hungarian: none / first / shipped |
|---|---|---|
| `gemma4:latest` | 11 / 2 · 11 / 0 · 13 / 0 | 7 / 3 · 6 / 0 · 7 / 0 |
| `qwen3.5:4b` | 8 / 0 · 8 / 0 · 7 / 0 | 4 / 0 · 7 / 0 · 7 / 0 |
| `gemma3:4b` | 13 / 0 · 12 / 4 · 12 / 2 | 8 / 1 · 9 / 0 · 8 / 2 |
| `qwen3:14b` | 7 / 0 · 6 / 1 · 7 / 0 | 7 / 2 · 7 / 2 · 6 / 1 |

Four things this says.

- **The letter-name failure was the pipeline's, not the model's.** Not one model gets a single
  prefix right until the bound title is in front of it — the 14B included, which is the best
  evidence that size was never going to fix it — and every model gets most of them right once it is.
- **The part-of-speech hint earns its place, but not where it was expected to.** On its own it fixes
  nothing. Alongside the title it is what stops a 23-sense page flooding the deck: `qwen3.5:4b`
  keeps 39 prefix cards with the title alone and 19 with the hint as well, and 302 glosses against
  271. On the nine-check Spanish benchmark it takes `gemma4:latest` from 7/9 to 8/9 (38 glosses to
  41) — it recovers `vaya` as the subjunctive of `ir` — and leaves `qwen3.5:4b` at 8/9 with five
  glosses fewer (52 to 47). Two small gains and no loss, so it stays.
- **Gender invention is a habit of some models and a hazard of the prompt.** `qwen3.5:4b` never
  writes a gendered rule for either language under any arm; `gemma4:latest` writes five without the
  paragraph and none with it; and the first wording *caused* four in `gemma3:4b` and one in
  `qwen3:14b`, which had written none without it. Over the eight model-language pairs: 8 gendered
  rules with no paragraph, 7 with the first wording, 5 with the shipped one.
- **How many senses a model keeps is its own habit, and pooling amplifies it.** `gemma3:4b` answers
  the pooled prefix pages with 48 cards for seven words — 25 of them for ל alone — and its Hebrew
  deck goes from 304 glosses to 428. The fix gives every model the right senses to choose from; it
  does not give a model the judgement to choose among them.

### The default, and the criterion it was picked on

**`qwen3.5:4b`, since 2026-09-15.** The criterion is the ceiling below: a deck may be slow but not
much slower than ten seconds a card, and *inside* the ceiling the scarce resource stops being the
clock and becomes the learner. So the default is the model that answers the most questions right and
hands the learner the fewest cards for doing it.

Measured cold — every answer re-asked — on the four-language benchmark in `tools/benchmark/`:

| model | passed | glosses for 24 sentences | cold wall | s/gloss |
|---|---|---|---|---|
| `qwen3:14b` | 23/24 | 412 | 1,142 s | 2.77 |
| **`qwen3.5:4b`** | **22/24** | 404 | **288 s** | 0.71 |
| `gemma4:latest` | 21/24 | 398 | 373 s | 0.94 |
| `gemma3:4b` | 16/24 | 500 | 293 s | 0.59 |

`qwen3.5:4b` is faster than `gemma4:latest` *and* answers one more question right, for six more
glosses in four hundred — and it fits the laptop, 3.3 GB against 9.6, which is what choosing gemma4
had cost. `qwen3:14b` buys one further answer for four times the wall clock; it is well inside the
ceiling and it is what `--model` is for. `gemma3:4b` fails a third of the checks and pays a hundred
extra cards to do it.

**This is the second change in two days, and the reason is worth keeping.** `gemma4:latest` was made
the default on the older benchmark — five Spanish sentences, nine checks — where all four models
scored 8/9 and the tie had to be broken on gloss count alone. Twenty-four checks over four languages
separate them by seven, and the separation does not run the way the tie-break assumed. A benchmark
that cannot distinguish its subjects will still produce a decision; it just will not be the right
one. See [The benchmark](benchmark.md).

### What decker can afford, 2026-09-15

Bru's ceiling: a deck may be slow, but not much slower than **ten seconds a card**. A run makes
roughly one model call per card — one disambiguation call per glossed occurrence, plus a rules call
per new inflected form — so that is a per-call budget, and these are the measured rates over the
tunnel to the GTX 2060, on uncached runs of the survey samples:

| model | seconds per call | a 300-card deck |
|---|---|---|
| `qwen3.5:4b` | 0.4 – 0.7 | 2 – 4 min |
| `gemma3:4b` | 0.6 | 3 min |
| `gemma4:latest` | 1.4 | 7 min |
| `qwen3:14b` | 2.6 – 3.8 | 13 – 19 min |
| `gpt-oss:20b` | 50 – 96 | **4 – 8 hours** |

The cliff is where the model stops fitting the card: `qwen3:14b` is 9.3 GB against 6 GB of VRAM and
still answers in seconds; `gpt-oss:20b` is 13.8 GB *and* wants to reason, and reasoning is not
optional for it — with thinking off it answers nothing at all. Low effort costs 50 s, medium 71 s,
high 96 s, so there is no setting that brings it inside the budget. What it buys is in
`morphological-rules.md`: it is the only model measured here that writes Turkish vowel harmony out
in full. It is not a model decker can use on this hardware, and that is the whole of the reason.

Local runs are capped — `OMP_NUM_THREADS=8` and `OLLAMA_NUM_THREAD=8` against 16 cores — because
Stanza builds its pipeline with no thread limit and torch will otherwise take all of them alongside
inference. The cap is about the machine staying up, not about speed.

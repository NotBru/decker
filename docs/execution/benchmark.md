# The benchmark: what a run is checked against

`docs/instructions/` is the source of truth: where this contradicts the design, the design wins and
this document is what needs correcting. The design says **"Do not test"**, and v1 still ships no unit
tests: nothing here asserts on decker's own functions. What lives in `tools/benchmark/` is a
different instrument — a **known-answer benchmark for the stage that has no right answer in the
code**, sense disambiguation, whose output is a model's judgement and can only be checked against a
reader's. Bru's instruction, 2026-09-15, is that it belongs in the repository rather than in a
scratchpad. If the design's line should be rewritten to say so, that is the human's to write.

## Why it had to grow

The benchmark it replaces was five Spanish sentences and nine checks, and by 2026-09-15 all four
models measured on it scored **8/9** — every one of them failing the same check. A measurement that
cannot tell its subjects apart has stopped being one. Bru's call: more sentences, more languages.

## What it is

`tools/benchmark/checks.json`: **24 sentences over four languages**, and **48 checks** — twelve per
language, doubled from 24 on Bru's instruction, 2026-09-17.

| | why it is in there |
|---|---|
| Spanish | a Romance baseline, and the language every other measurement here was made in |
| German | Germanic, heavy compounding, and nouns that are also names (`Wolf`, `Regen`) |
| Russian | Cyrillic, heavy inflection, and a vocabulary of clean homographs (`соль`, `есть`) |
| Chinese | no spaces, classifiers, and a section that covers a family of lects |

The sentences are Wikipedia lead text, CC BY-SA 4.0, and each language block names the articles it
was taken from. They were pulled by index from the samples the ten-language survey used, so no
sentence was transcribed by hand.

A check is a surface plus what the senses kept for it **must** and **must not** say — `media` must be
*average* and not *stocking*; `соль` salt and not the musical note; `Wolf` the animal and not the
constellation, the mincer or the surname; `есть` *to eat* and not the copula; `則` the classifier and
not *rule; law*. Every one was written against the sense list the page actually carries, read out of
the mirror first, rather than from memory of what the word means.

**The second twenty-four are checks, not sentences.** The same passages were read again for
ambiguities the first pass left on the table, which buys discrimination for nothing: no new text, no
new attribution, no longer run. They lean on the kinds of ambiguity the first set under-covered —
a taxonomic sense against an everyday one (`отряд` the order, not a military detachment; `género`
was already there), a word that is a word and a name (`juliana` from *juliano*, not the soup cut),
an auxiliary against a full verb (`werden` forming the passive, not the future), a form's own page
against its lemma's (`капель` the genitive plural of `капля`, not the dripping of thawing snow), and
a sense that the model has to *not* over-read (`durch` as *by means of*, not *through a door*).

`beber` is the one written for a stage rather than a language: `bebe de la tradición juliana` is the
figurative *draw from*, and since a marked sense now drags its plain sense into the deck with it
(`definition-fetching.md`), the check asks only that *draw from* is there and lets *to drink* stand
beside it. A `must_not` written the old way would have failed the pipeline for doing the right
thing.

**Three outcomes, not two.** A check whose term was never glossed is *absent*, not failed: it says
nothing about the model, and a great deal about the run. Term extraction quietly ceasing to produce a
term is exactly the failure a benchmark must be able to name rather than blame on the model — and it
caught one immediately, since a card is fronted with Wiktionary's spelling and the sentence-initial
`Хозяин` is glossed `хозяин`.

## How to run it

```
OLLAMA_HOST=... DECKER_WIKTIONARY_HOST=... \
    uv run python tools/benchmark/run.py gemma4:latest out.json
```

Concepts and rules are off, so the glosses are word senses and nothing else. It exits non-zero when
a check fails, which is the only respect in which it behaves like a test.

## What it says, 2026-09-17, on the 48 checks

| model | passed | failed | glosses | notes |
|---|---|---|---|---|
| `qwen3.5:latest` (9B) | **43** | 5 | **403** | 6.15 GB at runtime; **3.52 GB of it fits the card** |
| `qwen3.5:4b` | 42 | 6 | 416 | 3.13 GB, wholly resident |
| `gemma4:latest` | 40 | 8 | 409 | 9.6 GB on disk, 3.23 GB resident — an E-variant |

**One check, for ten times the wall clock.** The doubled set was meant to decide whether a bigger
model earns its keep on this hardware, and it says no. The honest timing is the cold pair, each
model asked every question for the first time: `qwen3.5:4b` **106s**, `qwen3.5:latest` **1045s** — a
GTX 2060 holds 3.5 GB of the 9B's 6.15 and pages the rest through system RAM. The warm re-runs in
the table above (259s, 458s, 826s) are parses, index scans and a handful of uncached calls, and are
not a speed measurement of anything.

Nor is it a clean upgrade. The 9B fixes `описать` (*to describe*, not *to take an inventory*) and
`年` (it stopped keeping three senses for `二十年`), and breaks `durch`, where *durch eine
Artenschranke getrennt* comes back *owing to; because of* and the 4B has *by means of*. It does keep
about 3 % fewer senses, which is 3 % fewer cards for the same text.

`gemma4:latest` is third on checks here as it was on the 24, so the ordering the old measurement
gave has held. It is the one that reads `Надежда казалась мне солью` as *hope* under every prompt
tried, which no check in this file asks about — a reminder that 48 checks over four Wikipedia leads
are not the whole of what a model does to a deck.

**`qwen3.5:4b` stays the default.** Bru, 2026-09-17: the 9B's one extra check is not worth ten times
the run.

## What it said, 2026-09-15, on the 24

| model | passed | failed | glosses for the 24 sentences | failures |
|---|---|---|---|---|
| `qwen3:14b` | **23** | 1 | 412 | 名 |
| `qwen3.5:4b` | **22** | 2 | 404 | italiano, 名 |
| `gemma4:latest` | 21 | 3 | 398 | italiano, 則, 名 |
| `gemma3:4b` | 16 | 8 | 500 | those three, plus gato, media, raza, Wolf, Form |

Wall clock is left out on purpose: `gemma4:latest` ran with most of its answers already cached and
its 52 seconds are not comparable to the others' 288, 293 and 1,142. `model-backends.md` has the
per-call rates, measured where they mean something.

**This reorders the models, and the old benchmark could not have.** Where nine Spanish checks gave
all four 8/9, twenty-four checks over four languages separate them by seven, and the separation does
not run the way the old one implied: `gemma4:latest`, made the default on 2026-09-15 for teaching a
text in the fewest cards, is third of four by checks — it saves six glosses against `qwen3.5:4b` and
gets one more answer wrong. The three good models are within two checks of each other, which on
twenty-four checks is one question in twelve; `gemma3:4b` is not close to them on either axis.


`gemma3:4b` answers the same 24 sentences with a hundred more cards than anyone else *and* fails
eight checks, which is the finding the old benchmark made with 110 glosses against 41, now with the
failures attached to it.

The failures that survive in the better models are worth reading. `italiano` in *la del italiano
Giambattista Basile* comes back as *Italian (language)* in three of four — the sentence names a man
and the models read a tongue. And **the classifier is what no Spanish benchmark could have found**:
`一名貧苦的少女` is read as *name* by all four, `一則民間故事` as *conjunction* or *rule* by two. A
classifier is a word that means almost nothing on its own and everything in its slot, and it is the
single hardest thing in this set.


## A deck read back by hand: Gokurakugai 0001, 2026-09-22

The 48 checks measure one stage against known answers. This is the other half of the question —
**what a finished deck actually reads like** — and it is a different instrument: one deck, read card
by card against the pages of the manga it was built from, with a judged sample rather than a stored
answer key. It belongs here because it is the only other thing in the repository that *scores*
anything, and because it caught failures no check in `checks.json` is shaped to catch.

```
OLLAMA_HOST=http://172.17.0.1:11435 uv run decker --target-lang ja --teach-script \
    --limit-glosses 1024 --name Japanese --out decks/japanese.apkg \
    decks/Gokurakugai/0001.mbz.zip
```

`qwen3.5:4b`, the default, over the tunnel to the GPU box. The deck is left in `decks/japanese.apkg`
(gitignored, like every deck). Wall clock is not reported here, and the 110 s this run took is not a
number: most of its answers were already in the cache. The timings are measured separately, below.

### What came out

| | |
|---|---|
| source | 443 speech bubbles, 5,063 characters, 443 sentences, 2,284 terms |
| read | 234 of the 443 sentences, which is where `--limit-glosses 1024` stopped it |
| glosses | 1,024 = **736 words, 257 symbols, 31 concepts**, of which 66 are etymological components |
| cards | **2,014** — 1,024 recognition, 990 production (the 31 concepts and 3 model-explained unknowns carry no pair) |
| folded | 11 symbol cards became the word card the text teaches the same character with |
| no entry | 16 words: 2 foreign and explained, 1 foreign and known, 1 native, 12 unrecognizable |
| coverage | of the 478 distinct term surfaces in the sentences read, **401 (84 %) have a card** |
| ordering | 4 glosses depend on a gloss with a higher index; **0 cards are studied before something they depend on** — the shuffle's topological sort absorbs it |
| what a card carries | 713 glosses with IPA, 526 with an etymology, 125 with a recording, 105 with an example |

The two fixes of the same morning are in it: `街` is *town, district, area* `[ɡa̠i]` with
`Kan’yō-on: がい (gai, Jōyō)` alone under it, and `Symbol: 極` carries `Go-on: ごく (goku, Jōyō)` and
nothing else. Across the deck, 54 symbol cards carry a single reading line and 128 carry the whole
list; of the one-character word cards, 127 carry one line and 26 the list.

### Sixty cards, judged in context

A seeded sample of 60 word cards, each read against the bubble it was first met in:

| | | |
|---|---|---|
| **right** | 43 | 72 % |
| thin or defensible | 6 | 10 % |
| **wrong** | 11 | 18 % |

*Thin* is a card that is not wrong and teaches nothing much: `もの — (conjunctive)`, `なの` labelled
*chiefly women's speech* under a man's line, `おわす` glossed correctly as a dependency of ござる that
the text never needed.

**The eleven wrong ones do not have one cause, and only four are the model choosing a sense.** That
is the finding, and it says where the next work is:

| what went wrong | n | the cards |
|---|---|---|
| the sense chosen for a word that really is there | 4 | `消える — to die` (人が消える is *vanish*), `成る — to be acceptable` in 世話になってる, `吐く — to confess` for 嘘を吐く, `電 — lightning` inside 電話 |
| the parse produced a word that is not there | 3 | `成る` out of the stutter なっなななんなん, `ら — imperfective of る` out of the elongated なーら, `つい — inadvertently` out of について |
| a dependency judged against a passage it does not appear in | 3 | `小さい` and `と`, both dependencies of ちょっと and disambiguated against the one-word bubble 「ちょっと」; `しまう — to close` reached from ちゃう |
| the surface's page beat the lemma's | 1 | `せ — rapids, current` for the causative せ of 言わせる, whose own entry せる was in the same candidate listing |

Manga is what makes the second row: speech is drawn, not typed, and elongation (`なーら`,
`わっかるー`), stuttering (`なっなな`), and set phrases split at the wrong seam (`について`) are what a
dependency parser meets in a bubble and not in Wikipedia. The OCR adds its own — `鯉` glossed as
*the common carp* comes from a bubble mokuro read as 極楽街**鯉**決事務所, and `玉 — a female
entertainer` from `＃玉大ＵＩＫ`. Neither is decker's mistake and both are cards in the deck.

### What a scan of all 1,024 says

Four defects are countable without judgement, and each is a class rather than an accident:

- **4 cards whose definition is Wiktionary's maintenance boilerplate** — `饅 — This term needs a
  translation to English. Please help out and add a translation`, and the same on `雪`,
  `Symbol: 旋`, `Symbol: 捕`. A sense that asks the reader to edit Wiktionary is not a sense.
- **5 cards whose only sense is onomastic** — `最 — a male given name[2]`, `近 — a surname`,
  `友`, `西`, `雪`. Two of them are right (`西雪春` is a character's name); the other three are
  components of 最近, where the name sense is the one thing the compound cannot mean.
- **7 cards for rōmaji transcription entries** — `a`, `an`, `no`, `do`, `you`, `hiragana`,
  `katakana`, each *Rōmaji transcription of …*. They arrive as dependencies: `ィ`'s definition
  mentions katakana, the form-of reader takes the word, and the page it reaches is the Latin
  spelling's. A card fronted with the English word `you` in a Japanese deck is never right.
- **185 cards above one per surface.** 114 of the 551 distinct word surfaces kept more than one
  sense — に has 10 cards, て 9, 前 6 (*a portion*, *the front*, *the past*, *the last*, *ago*,
  *previous*). By the tag the parse gave the term: NOUN 45, VERB 31, ADP 26, AUX 24, PART 13. A
  fifth of the word cards in the deck are a second or third sense of a word already taught, and the
  particles are where it concentrates — which is the Hebrew-prefix finding of `definition-fetching.md`
  turning up in another language with another cause.

**No `Rule:` card appears in this deck at all**, though `--no-rules` was not passed. 59 glosses are
form-of lines, but a rule's card waits for a second instance of the same bundle and none reached one
inside the 1,024. The store `~/.cache/decker/rules/ja.json` does hold two rules from earlier
sessions, and the second is worth reading: *"take any verb, change its final letter to 'te' … 'taberu'
→ 'tabete' → 'tabeteku'"*, on a base recorded as `a`. Rule cards are written by the model out of an
inflection line and say so on the card; this one is a fabrication, and Japanese is where the stage
should be looked at next.


## The other clock: what a run costs, 2026-09-22

Sense quality is one axis and wall clock is the other, and a deck nobody waits for is not a deck.
The measurement here is of decker rather than of a model, so it is the one thing in this file that
is not a judgement: the same work, the same caches cold, the code before a change and after it.

**What was already known** (profiled 2026-09-21, py-spy at 25 Hz, flamegraph kept out of the
repository in `~/.cache/decker/profiles/`): a cold build of this deck with `--limit-glosses 1024`
took **1,926 s** and was **97.8 % blocked on two sockets that never talk at the same time** —
ollama 1,047.7 s (54.4 %), Wikimedia 830 s (43.1 %) — with about 43 s of CPU in the whole run.
Optimising decker's own Python was never going to matter; the two remote machines taking turns was.

Three changes, all of them the plan that profile produced:

- **One connection per origin, not one per request.** `pages._fetch` built a fresh
  `urllib.request` every time, so every page paid DNS, TCP and a TLS handshake again — 186 s of
  that 1,926, measured directly (getaddrinfo 33.7 s, create_connection 88.3 s, do_handshake 63.8 s
  over 968 requests). It is now one kept-open `http.client` connection per origin, per thread,
  dropped and remade when the other end has closed it.
- **A prefetcher two sentences ahead of the gloss loop**, on two threads (`_Ahead`). It fetches the
  pages the coming terms will need — including the character pages a `--teach-script` run wants,
  which were 16 % of the Japanese network time — and asks the sense question those terms will be
  asked, and throws both answers away. What it fills is the page cache and the answer cache; the
  loop finds them there. It computes no gloss, holds nothing the builder reads, and a prompt is a
  pure function of the page and the passage, so a question asked ahead is the same question.
- **Two questions in flight instead of one**, which falls out of the same two threads: the box
  answers at 0.71 s a question asked serially and **0.45 s at two**, flat at four and six (measured
  against fesat with `qwen3.5:4b`; the ceiling is the GPU, not admission control). A question
  already in flight is now waited for rather than asked twice, since a cache file that does not
  exist yet cannot dedupe anything.

**The connection, measured on its own.** Thirty titles each, the two paths interleaved inside one
process so that neither arm gets a warmer Wikimedia than the other — because the first pass over a
title pays for the render and the second does not, which is what made the first attempt at this
measurement say the opposite of the truth:

| a page fetched through | mean | median | 30 titles |
|---|---|---|---|
| a fresh connection, as before | 1.003 s | 0.788 s | 30.1 s |
| **a kept connection** | **0.664 s** | **0.561 s** | **19.9 s** |

**All three, end to end.** The same workload each time — `deck --target-lang ja --teach-script
--limit-glosses 256` over `0001.mbz.zip` — with `DECKER_CACHE_DIR` pointed at an empty directory, so
every page and every answer is fetched and asked for the first time. A throwaway run went first so
that Wikimedia's own cache was warm for both:

| | wall clock | glosses | cards | pages fetched | questions asked |
|---|---|---|---|---|---|
| before | 403 s | 260 | 506 | 245 | 172 |
| **after** | **232 s** | 258 | 502 | 248 | 172 |

**1.74×**, and 1.8× on the glossing stage itself: 21 s of each run is the parse, the title index and
term extraction, which none of this touches. The two runs differ by two glosses because each asked
the model afresh and a GPU batches differently at concurrency two — which is the reason the honest
check of *sameness* is the other one: **given the same caches and the same `--seed`, the deck the
new code writes is byte-identical to the deck the old one writes.**

What is left is what the profile said would be left: at 232 s this run is mostly fesat generating
tokens, and the levers after that are a smaller model, a better card, or asking fewer questions.

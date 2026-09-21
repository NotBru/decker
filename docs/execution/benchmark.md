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

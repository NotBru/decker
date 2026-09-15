# Deck growth

`docs/instructions/` is the source of truth: where this contradicts the design, the design wins and
this document is what needs correcting. This one records a measurement rather than a decision — what
a deck costs as the text it is built from grows, with concept cards and with morphological rules —
so that the two stages that were built on an argument can be checked against a number.

## The question

Both later stages were argued for rather than measured. Concept identification adds cards nobody
asked for: the terminology a definition is written in. Morphological rules add cards *and* take
cards away, and the claim made for them is that the second eventually outweighs the first — "the
tenth such card teaches nothing the second did not". Neither claim had a curve behind it.

So: read one corpus straight through, three times over, and count the deck after every sentence.

- **words only** — `--no-concepts --no-rules`, the deck the first version made.
- **+ concept cards** — concepts on, rules off.
- **+ morphological rules** — both on.

## How it was measured

Definition fetching walks the sentences in order and appends a gloss the first time its (form,
sense) pair is met. The glosses standing after sentence *N* are therefore exactly the glosses a run
over the first *N* sentences would have produced, and counting after each sentence is the same
measurement as *N* separate runs — at 1/*N* of the cost. That matters for more than speed: the
rules stage's culling counters are per-run by design, so the whole corpus has to be read in one
continuous pass for them to mean anything.

One builder and one `Morphology` span the whole corpus, and the rule book starts empty. This is one
learner reading nine texts in order, not nine decks.

## The corpus

Nine Spanish sources, 12,022 words, 907 sentences: `barbapedro` first, because it is the text the
earlier graphics were made from, then the eight stories of Quiroga's *Cuentos de la selva* (1918,
public domain) in the book's order. Each Quiroga story is cut at a paragraph boundary near 1,400
words so that no source dominates; `barbapedro` is 906 and is left whole.

Pages came from the local Wiktionary mirror (`docs/execution/local-wiktionary.md`), so the run was
silent and nothing about the vocabulary left the machine. The model was `gemma4:latest` over the
tunnel; audio was off.

## What came out

| after | words | words only | + concepts | + rules | saved | rule cards | rules known |
|---|---|---|---|---|---|---|---|
| barbapedro | 906 | 1,040 | 1,079 | 1,025 | 5.0 % | 24 | 31 |
| tortuga | 2,305 | 1,954 | 2,002 | 1,796 | 10.3 % | 32 | 49 |
| flamencos | 3,660 | 2,800 | 2,856 | 2,479 | 13.2 % | 43 | 59 |
| loro | 5,053 | 3,482 | 3,541 | 3,005 | 15.1 % | 48 | 64 |
| yacarés | 6,454 | 4,032 | 4,093 | 3,420 | 16.4 % | 53 | 68 |
| gama | 7,846 | 4,678 | 4,742 | 3,877 | 18.2 % | 57 | 77 |
| coatí | 9,237 | 5,170 | 5,236 | 4,228 | 19.3 % | 60 | 84 |
| yabebirí | 10,627 | 5,630 | 5,696 | 4,565 | 19.9 % | 63 | 84 |
| abeja | 12,022 | 6,184 | 6,251 | **4,949** | **20.8 %** | 66 | 93 |

"saved" is the third deck against the second, which is the honest comparison: both carry the concept
cards, and only the rules stage differs.

Four graphics, written beside the CSVs the numbers come from:

- `growth-cards.png` — the three decks against words read, with two reference lines: one card per
  word, and the deck if no form and no sense were ever met twice.
- `growth-rate.png` — what the next word costs, as a rolling mean over fifteen sentences.
- `growth-composition.png` — the third deck cut into word cards, concept cards and rule cards.
- `growth-savings.png` — what the rules stage removed, what it added, and the difference.

## What it says

**Concept cards are almost free, and they stop.** Sixty-seven cards over twelve thousand words —
1.1 % of the deck. Thirty-nine of them were already standing after the first source, and the next
eleven thousand words added twenty-eight more. That is the shape the design predicted: the
terminology a dictionary writes definitions in is a closed set (`Appendix:Glossary` has 622
entries), so this curve flattens where the vocabulary curve does not. The cost of the stage is
bounded and small; the argument for it never has to be an argument about size.

**Morphological rules cost first and pay later, and the crossover is early.** Rule cards are the
cost and they flatten too — 66 cards, for 93 rules worked out (a rule whose second instance never
arrives gets no card). The culling is the return, and it does not flatten: it grows with every
source, because every new source is mostly inflected forms of a language whose regularities have
already been written down. On the first source the stage was already ahead, 1,025 cards against
1,079; by the ninth it was 4,949 against 6,251.

**The saving is still growing at 12,000 words, but it is decelerating**: 5.0, 10.3, 13.2, 15.1,
16.4, 18.2, 19.3, 19.9, 20.8 %. The marginal figure is the sharper one — over the last source alone,
the deck with rules took 0.27 cards per word where the deck without took 0.40, a third less. A
learner reading further into the same language keeps getting that discount; the cumulative
percentage lags it because the early, rule-less part of the deck stays in the denominator.

**A deck was never linear in the text anyway.** Twelve thousand words produced 6,184 cards without
the rules and 4,949 with them, against 21,000-odd if nothing were ever reused. Most of that was
already true before either stage: reuse is what the (form, sense) identity buys.

## Why the saving stops at a fifth

The 20.8 % is real but it is nowhere near "one card per rule". Replaying the run with every
morphology decision recorded — the replay reproduces the rule book byte for byte, so it is the
same run — says where the rest goes.

**Only 41 % of the deck is eligible, and that is the whole ceiling.**

| | glosses |
|---|---|
| word glosses in the +concepts deck | 3,092 |
| ordinary definitions — a noun, a verb in citation form, a word pulled in as another gloss's dependency | 1,809 (59 %) |
| form-of lines — everything the stage can ever touch | **1,283 (41 %)** |
| of those, removed | 684 (53 % of the ceiling) |
| of those, survived | 599 |

No rule can remove an ordinary definition, because there is no rule to state: `pájaro` is a word
to learn, not a regularity. So even culling *every* inflected form in the corpus would only take
the deck from 6,251 to 3,751 — **40 %**, not 100 %. Against that ceiling, 20.8 % is a little over
half of what was available.

**Irregularity is not the limiter.** Of 1,226 distinct forms put to the stage, 1,194 (97 %) came
back covered by a rule and only 32 got none at all. The model almost never says "irregular" — the
generosity already recorded in `morphological-rules.md`, now measured.

**The pacing is where the rest goes.** 93 rules matched something, but 51 of them cover four
distinct forms or fewer — under the "keep the first four" floor, so they cull nothing at all, and
their 94 forms are every one taught. The floor keeps a further 264 instances outright. The
long tail of rules is the problem: the ten biggest rules account for almost all the culling, and
half the book never reaches the threshold at which culling begins.

**And the run's own `culled` figure overstates the saving by 1.7×.** The report says 1,154
inflected forms left out. Those are 1,154 *occurrences*, over 754 distinct forms, and 85 of those
forms are in the deck anyway: a culled occurrence is never written into `seen`, so the next
occurrence of the same form is put to the stage again and the halving schedule eventually lets it
through. The honest number is 669 glosses removed, 1,338 cards, less the 66 rule cards. Worth
either fixing the counter's wording or making a cull stick — see below for what the latter buys.

**Tuning the schedule barely moves it.** Simulated over the recorded decision stream:

| policy | deck | vs +concepts |
|---|---|---|
| as shipped (keep the first 4, halve every 4) | 4,949 | 20.8 % |
| a cull sticks: a culled form is never re-offered | 4,873 | 22.0 % |
| halve every 2 instead of 4 | 4,677 | 25.2 % |
| keep the first 2, halve every 2 | 4,619 | 26.1 % |
| both of the above | 4,585 | 26.7 % |
| no pacing at all — one card per rule, ever | 4,375 | 30.0 % |

The entire pacing knob, turned all the way to its most brutal setting, is worth nine points. The
eligibility ceiling is worth sixty. **If the deck is to get much smaller, the lever is not the
culling schedule — it is the 59 % that are ordinary definitions**, and those are the vocabulary
the design exists to teach. The design's real size dial is elsewhere: every one of those 1,809
glosses is a *pair*, and rule and concept cards already show that a single card is allowed.

## What this does not say

- **Nothing about whether the rules are any good.** The stage was measured on how many cards it
  makes and unmakes, not on whether what it writes is true. Spot-reading the Spanish rule book turns
  up correct ones (`conocer` → `conocí`, "for -er verbs, change -er to -í") beside plainly wrong ones
  (`gallo` → `gallito` described as "masculine nouns ending in a consonant … adding -illo", which is
  wrong about both the class and the ending). The economics here hold whatever the prose says; the
  prose is a separate measurement, and the model is the ceiling on it. See
  `docs/execution/morphological-rules.md`.
- **Nothing about a second run.** A deck is a function of the text *and* the rule book, and the book
  grew throughout this one. Re-reading the same corpus against the finished book would cull earlier
  and save more; the numbers here are the pessimistic ones, from a cold start.
- **One model, one language.** `gemma4:latest` and Spanish. The cross-language picture is in
  `docs/execution/language-survey.md`.

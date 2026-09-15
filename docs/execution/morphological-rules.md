# Morphological rules

The human documents outrank this one. `docs/instructions/v1/design.md` specifies this stage; what
follows is what building it decided, and where the design left a choice open, which way it was taken
and why.

The stage lives in `decker/morphology.py`, is consulted from `decker/glosses.py`, and is turned off
with `--no-rules`.

## What the design asks for

A rule takes a base word — the lemma, or whatever a form is derived from — to a feature bundle,
"Wiktionary's form-of prose, normalized to their concept". A database keeps the bundle, a
representative word, the rule's description and the target language. For each new word the model is
asked whether any existing rule applies; if none does, whether a regular rule exists at all; if one
does, the word becomes the representative of it and the model writes it down. Instances are then
culled — the first four kept, the frequency halved every four shown — and the explanation card
depends on the first two instances, so it arrives only after the learner has met them. Rules carry no
production pair, and are translated to the mother language.

## The choices

### The feature bundle is the sense's glossary anchors, canonicalized and sorted

"Normalized to their concept" already has a mechanism behind it: concept identification reads the
`Appendix:Glossary` links Wiktionary puts inside a definition, and several anchors resolve to one
entry (`first_person`, `1st_person`). So a bundle is the set of glossary entry *names* a form-of
sense links, sorted — sorted because the order a definition names its features in is the definition's
business, and `first-person singular preterite` and `preterite first-person singular` have to be one
bundle or the database fills up with duplicates.

The bundle is the identity; what a card shows is `label`, which is Wiktionary's own prose with the
`of <base word>` cut off it — "first/third-person singular imperfect indicative". Canonical for
matching, readable for a human.

Under `--no-concepts` the glossary is never fetched, and the raw anchors are used instead, spaces for
underscores. The bundles are then coarser than they could be — two spellings of one feature no longer
collapse — and never wrong. Fetching the glossary anyway would have made `--no-concepts` fetch the
page it exists to avoid.

The visible cost is that a `--no-concepts` run and an ordinary one write *different* bundles for the
same grammar — `indicative` against the glossary's `indicative mood` — so the book ends up holding
both, and each run reuses its own. Measured on the same seven sentences: three extra rules, no
change to what reached the deck. Rules are cheap and the book is a cache; a bundle that silently
matched under one flag and not the other would not be.

### One rule per (bundle, representative), and the representative is in the card's title

Several rules per bundle is the design's own example (the Spanish gerund is `-ando` or `-iendo`
depending on the base word's class), so the bundle alone cannot identify a rule. The representative
completes it, and it also goes in the card's title —

```
Rule: first/third-person singular imperfect indicative (vivía)
```

— because a learner meeting the second rule of a bundle needs to see at a glance that it is not the
first one again.

### "Any of the existing rules" means the bundle's rules, in this language

Bru's decision, taken before the build. A rule for the diminutive has nothing to say about a
preterite, and asking a small model to rule it out is a call spent to learn nothing. `RuleBook.matching`
is the whole of it.

### Two prompts, and neither is asked when its answer cannot matter

`PROMPT_APPLIES` is skipped when the bundle has no rules yet — there is nothing to apply — and
skipped again when the word *is* a rule's representative, which obeys it by construction.
`PROMPT_REGULAR` is asked only when the first found nothing. A word met twice is decided once
(`Morphology.decided`), and every answer goes through the same on-disk answer cache as
disambiguation and translation, so a second run of the same text asks nothing at all.

Both prompts put their fixed instructions first and their variable parts last, so consecutive calls
share as long a prefill as ollama can keep — the same shape, and for the same reason, as the other
two stages' prompts.

### The prompt names the categories the language actually has

The ten-language survey found the model stating rules over a gender the language does not have —
Turkish "for **feminine** nouns, add the ending -ın to form the genitive singular", Hungarian "for
nouns that are **masculine**, the singular form is created by adding -a". The endings are often
right and the class is invented, which is the worst shape a wrong card can take: it teaches a
distinction the language does not make, and a learner has no way to see that from the card.

The parse already knows. Stanza marks the categories a language inflects for on every word it reads,
so a category marked nowhere in a whole text is one the language does not have — for the pervasive
six, at least (gender, number, case, person, tense, definiteness), which are marked on nearly every
word that could carry one. Term extraction collects the names off the tokens it covers,
`glosses.build` unions them over the text, and `PROMPT_REGULAR` gains a paragraph naming both
halves: what the language marks, what it never marks, and not to state a rule over the second.

Three things were deliberately left out:

- **The rarer categories.** Aspect, voice, animacy and degree are neither claimed present nor
  claimed absent. Absent from 2,500 characters they may be absent from the sample only, and a prompt
  that says so with confidence would be worse than one that says nothing.
- **Any paragraph at all when there is nothing to warn about.** A language marking all six — every
  European language in the survey but the two agglutinative ones — gets the prompt exactly as it was,
  because the inventory could only tell the model things it is not getting wrong. It costs the
  languages that do not need it nothing.
- **Any paragraph when the parse marked none of them.** Japanese marks none of the six, and the
  honest reading of that is that the parse has nothing to say about the language, not that the
  language has no grammar.

**Mood was in the list and was taken out**, which is what keeping the list short is for. Run over
all ten samples it came back absent for Dutch and Hebrew, both of which have an imperative: UD
treebanks mark `Mood` sparsely, so the absence is the treebank's habit and not the language's. The
other six came back absent only where the language really has nothing — gender in Hungarian,
Turkish, Japanese and Chinese, definiteness in Turkish, tense in Chinese — which is the check this
kind of table needs before it is allowed to tell a model anything.

### Irregular means: no rule, and a card forever

A model answering "not regular" leaves the word with the ordinary form-of card definition fetching
already built. It obeys nothing, so no culling can ever cover it, which is exactly right: an
irregular form is not derivable and has to be met. A "regular" answer with an empty rule is treated
as irregular too — there is nothing to teach, and a rule card with an empty back is worse than no
card.

### The culling counts live in the run; the rules live in the cache

The rule database is `~/.cache/decker/rules/<lang>.json`, written atomically after every new rule
(the run is minutes of local inference on a machine that has lost power mid-call; a rule is a model
call that should not have to be spent twice). It is knowledge about the language, so the next text in
the same language starts with every rule the last one worked out, and deleting it costs only the
calls that made it.

The culling counters are deliberately *not* persisted. They pace one deck: how many instances of a
rule this deck shows, and how far apart. A cache that decided which cards a deck contains would no
longer be a cache — deleting it would silently change the output — and a second deck over a new text
is a new first week, not a continuation of the last one's.

### The instance that is culled is the inflected form's card; the base word's card stays

The design says so in as many words, and it is the point of the whole stage: after the rule and a few
examples, `bajaba` is derivable from `bajar`, and `bajar` is what still has to be learned. In the code
the base word's gloss is built *before* the culling decision is taken, so that the two can never come
apart by accident.

A culled instance is simply never added, which also means its concepts are not glossed from it. They
will have been glossed from the instances that were kept — a bundle's terminology arrives with its
first example.

### Only occurrences in the text are instances

A word reached through a definition — the `vivir` that `vivía` is explained in terms of — is a
dependency, not an instance. Culling one would take away the very card the design told us to keep.

A form met again in the same sense is not a new instance either: it is one card however many times
the text says it, so it moves no counter and cannot be one of the rule card's two examples.

### The rule card is appended at its second example, not at its first

The explanation card depends on the first two instances. Deck construction resolves a gloss
dependency to the card that introduced it, and it can only do that for glosses it has already seen —
so a rule card appended when the rule was *created* would be pointing at a gloss that does not exist
yet, and the dependency would be silently dropped. Appending it at the second example makes both
dependencies point backwards, and the shuffler's topological sort does the rest. Nothing in
`shuffling.py` had to change.

The consequence: a rule with only one instance in this text produces no card. That is the design's
constraint read strictly — a rule stated after one example is a generalization from one example — and
the rule itself is still written to the database, so the next deck can teach it.

### A rule card carries no production pair, like a concept card

`Gloss.production` now says this outright, and `cards.py` reads it instead of testing whether the
gloss has a glossary anchor. The design gives the pair to word definitions only. Producing a rule's
title from its description would be a question about decker's own titling.

### A rule's prose is not Wiktionary's, and the card says so

Every other card quotes Wiktionary under CC BY-SA and credits it. A rule is written by the model
*from* an inflection line, which is a different claim, so rule glosses carry an `attribution` —

> Rule written by qwen3.5:4b from Wiktionary's inflection line, not quoted from it.

— which the Anki credit and the Markdown document show in front of the usual entry credit. The entry
still names and links the representative's page, which is where the rule came from.

### Translation comes free, except for titles

A rule's description travels in the gloss's `definition` field, so deck construction translates it
with everything else and the design's "the rules should be translated" needs no code of its own.

Card *titles* are not translated — not a rule's, and not a concept's either, which the design does ask
for. That gap predates this stage and is unchanged by it.

## What it costs, measured

Seven sentences of barbapedro, Spanish, `qwen3.5:4b` on the laptop's CPU, 2026-09-13:

| | with the stage | `--no-rules` |
|---|---|---|
| glosses | 122 | 120 |
| of them rule cards | 4 | — |
| inflected forms culled | 2 | — |
| model calls | 92 disambiguation + **18 rules** | 92 |

So the stage costs about a fifth again on top of disambiguation's calls, and it costs them once per
*form* rather than per occurrence: 18 calls covered every inflected word in the text, and a second
run over it asks nothing, because the answers and the rules are both cached. The whole first run
took 11m14s including the page fetches for five new sentences; the same run with everything warm is
21s, against 15s with `--no-rules`.

It wrote five rules, four of which reached a second example and so became cards:

```
vivía   <- vivir    first/third-person singular imperfect indicative
gallito <- gallo    diminutive
pintado <- pintar   past participle
muchos  <- mucho    masculine plural
pájaros <- pájaro   plural
```

### What the model gets wrong, in this run

`qwen3.5:4b` is generous with "does this rule apply". Asked whether `era` (of `ser`) obeys the rule
written from `vivía` — "for verbs ending in -ir, add -ía to the stem" — it said yes, and `sus` was
accepted as an instance of "the plural of masculine nouns ending in a vowel". Both are wrong, and
the second question, "is this regular at all", is answered more soberly than the first.

The cost of a wrong yes is bounded and one-sided: the word joins a rule's instance count, so after
four instances it may be culled and the learner loses a card they cannot derive. The cost of a wrong
no is an extra rule card. Neither corrupts the rest of the deck, and a better model changes both
without a code change. This is the stage's real accuracy ceiling, and it is the model's, not the
pipeline's.

### What naming the categories changed, measured — and what it did not

`gemma4:latest`, the model the survey ran on, over the survey's Turkish and Hungarian samples, with
the paragraph and without it and nothing else different. Every run starts from an empty rule book,
so "rules written" means the same thing in both:

| | rules written | stated over a gender the language lacks |
|---|---|---|
| Turkish, with the inventory | 13 | **0** |
| Turkish, without | 11 | 2 |
| Hungarian, with the inventory | 7 | **0** |
| Hungarian, without | 7 | 3 |

The arm without it reproduces the survey's own sentences word for word, which is the useful part —
the same model, the same words, the same bundles, and the failure appears and disappears with the
paragraph:

```
kızın   <- kız    "For feminine nouns, add the ending -ın to form the genitive singular."
                  "For singular nouns, add the suffix -ın to the base word to form the genitive case."
annesi  <- anne   "For feminine nouns, add the suffix -si to form the third-person singular possessive."
                  "For nouns, add the possessive suffix -si to form the third-person singular possessive."
fivérek <- fivér  "For masculine nouns ending in a consonant, the nominative plural is formed by adding -ek."
                  "For nouns, the nominative plural is formed by adding the ending -ek to the base form."
```

**It is not a general fix, and the wording is most of it.** Asked of four models
([Model backends](model-backends.md) has the table), the first version of the paragraph *caused* the
invention in two of them: `gemma3:4b` wrote four gendered Turkish rules with it and none without,
`qwen3:14b` one with and none without. That version ended "an ending that applies to feminine nouns
cannot be the rule in a language without gender" — the sentence telling a model not to say *feminine
nouns* was the only place in the prompt those words appeared. Rewritten to say the same thing
without naming a class, the totals over eight model-language pairs are:

| | gendered rules, all four models, Turkish and Hungarian |
|---|---|
| no paragraph | 8 |
| the first wording | 7 |
| the wording that ships | **5** |

Five is not zero. `gemma3:4b` still writes two gendered Turkish rules and two Hungarian ones with the
paragraph in, having written none without it; a 4B model told that a language has no gender is still
capable of writing a rule about masculine nouns two sentences later. What the paragraph reliably does
is fix the model whose failure motivated it, and it is measured rather than assumed for everything
else.

What it does not fix is everything else the prose gets wrong, and that is worth being plain about.
Turkish vowel harmony is still named once and never explained; a bundle Wiktionary labels oddly
still produces "the second-person singular imperative is formed by adding the ending -", which is a
rule about nothing. The inventory removes one specific invention — a class of base word the language
does not have — and leaves the accuracy ceiling above exactly where it was.

### Does a bigger model write the prose properly? Partly, and not at a price this hardware can pay

The expectation worth testing was that the prose failures are a small-model problem. To ask it
without running the pipeline behind a model too slow to finish one, `_ask_regular`'s inputs are
captured once — they are a pure function of the text and the pages — and replayed to each model:
47 questions from the Turkish sample, 31 from the Hungarian, the same questions for everyone, with
the inventory paragraph and without.

| model | gendered rules, no paragraph | with it | names vowel harmony (tr) | states its alternants (tr) | seconds per call |
|---|---|---|---|---|---|
| `qwen3.5:4b` | 0 | 0 | 1 | 1 | 0.4 – 0.7 |
| `gemma4:latest` | 10 | **0** | 0 | 2 | 1.4 |
| `qwen3:14b` | 4 | 3 | 8 | 1 | 2.6 – 3.8 |
| `gpt-oss:20b` | — | — | (see below) | (see below) | 50 – 96 |

Two different things, and only one of them is about size.

- **Inventing a gender is a per-model habit, and it is not size-ordered.** The 8B invents it ten
  times and stops completely when the prompt names the categories; the 4B never does it at all; the
  14B does it four times in Hungarian and keeps doing it three times with the paragraph in. A bigger
  model is not the fix, and neither, for every model, is the paragraph.
- **Stating vowel harmony does improve with size, and the 14B is where it stops being useful.** It
  *names* harmony eight times — "the suffix follows a vowel harmony rule", which is the survey's
  complaint verbatim — and gives the alternants once. `gpt-oss:20b`, asked the same first question,
  answers:

  > For a noun in singular, add the genitive-case suffix. The suffix is written as –ın, –in, –un or
  > –ün, chosen by vowel harmony: use –ın after a back unrounded vowel, –in after a front unrounded
  > vowel, –un after a back rounded vowel, and –ün after a front rounded vowel.

  That is the card the survey said was missing, written without being asked twice.

**And it costs 96 seconds.** 50 at low reasoning effort, 71 at medium, and `gpt-oss:20b` answers
*nothing at all* with reasoning off (`model-backends.md`). Bru's ceiling, 2026-09-15: a deck may be
slow, but not much slower than ten seconds a card. Against that, everything up to the 14B fits with
room — 0.4 s a call for the default, 3.8 s for the worst of the 14B's — and a 20B reasoning model is
five to ten times over it at every setting there is. So the rule prose stays where
`language-survey.md` found it: better models write it better, the best one measured here writes it
properly, and none of them is affordable on the hardware decker runs on. That is a hardware
statement, not a design one, and it will age.

## The deck is a function of the text *and* the book

Worth knowing, because it looks like non-determinism: the rule book grows **during** a run, so a word
asked before its bundle had any rule is asked a different question than the same word asked after.
The first run over this text and the second differed in four places — the imperfect rule card moved
earlier, and `pasaba`/`hablaba` were culled where `codeaba`/`bajaba` had been. The third run was
byte-identical to the second: once the book holds every rule the text needs, the run is stable, and
the drift is the book converging rather than the model wavering.

That is the design's own shape — an incremental database consulted per word — so it is accepted
rather than worked around. What it means in practice is that a deck rebuilt after the book has grown
can lose an inflected form it used to teach; `--previous` is the answer, since a card already taught
stays taught and the rebuild only adds.

## What it does not do

- **No morphological analysis of decker's own.** Whether a rule applies is the model's judgement,
  and a small model will sometimes say that a stem-changing verb obeys the regular rule. The cost of
  a wrong yes is a card the learner cannot derive; the cost of a wrong no is one extra rule card.
- **The base word is the first word the form-of line names.** `glosses.py` already parsed it for the
  dependency, and this stage reuses exactly that; a line naming two words gives the first.
- **Rules are per target language, and never shared between languages.** The database is keyed by
  language and so is every rule in it.

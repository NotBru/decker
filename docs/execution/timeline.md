# When can I watch this: a deck read back against its subtitles

Written by an AI agent, not by hand. It records the choices taken while building `decker timeline`,
which reads a `.apkg` back against the subtitle file it was built from and says how far into the
deck a viewer has to be to have met the words said up to each timestamp. The design documents remain
the source of truth: where this contradicts them, the design wins and the code is wrong.

Bru asked for it on 2026-09-18, for the Russian deck: *how long until I understand up to that
point*.

## What it is

```
uv run decker timeline --target-lang ru --deck decks/russian-v3.apkg episode.srt
```

```
    up to    cues   words  no card    95% by   days      all by   days
------------------------------------------------------------------------
 00:30:00     508    1375       49     2762    138.1       11481    574.0
 01:00:00    1037    2143       73     4230    211.5       12425    621.2
 ...
 06:37:53    7229    6528      194    12627    631.4       12912    645.6
```

One row per `--every` seconds, the last row being the end of the last cue so the table's final line
is the whole file. Reading across: by this timestamp the file has said this many distinct words —
senses, plus the concepts and rules their definitions rest on — of which this many are in no card of
this deck; to have been taught 95% of them you must be 2,762 cards into the deck, which is 138 days
at 20 new cards a day; the last of them sits at 11,481, which is 574.

`--format csv` and `--format json` give the same rows for plotting. `--cover` moves the share,
`--rate` the cards a day, `--every` the row size.

## The unit, and what is not claimed

The deck's order is the answer's denominator. Decker knows the order of the cards and nothing about
how fast their owner studies, so what it reports is a **position in the deck** — *you must have
studied this many cards* — and days are that position divided by `--rate`, defaulting to Anki's own
20 new cards a day. It is a division, not a prediction: no review load, no forgetting, no days off.

Nor is it a claim about understanding. A card is a word met once, not a word known; the deck teaches
a text's words and not its grammar; and 95% of the words is not 95% of the meaning. What is measured
is coverage of the deck's own material, which is the strongest thing the data supports. The column
headings say `by card` and not `understood`, deliberately.

## Why the headline is a share and not the last card

The obvious metric — the furthest card among the words said so far, "study this much and you have
met all of it" — is the one the request literally asks for, and measuring it is what ruled it out as
the headline. On the Russian deck the furthest card needed for the **first ten minutes** is 6,103 of
12,913, and by twenty minutes it is 11,481: nine tenths of a deck for a fifth of an hour, and then
essentially flat for six more hours. That curve answers no question.

It is not noise in the measurement. Tracing it: `лет`, said at 08:59, is taught by card 6,103;
`фильмы`, in the very first cue, by card 5,597. Both are inflected forms. The rules stage culls
instances of a form once the rule behind it has been shown — the first four, then half as often
every four (`morphological-rules.md`) — so the early occurrences of such a form make no gloss at
all, and the deck teaches it from whichever later occurrence survives the cull. Its card is
therefore placed where that occurrence is, not where the viewer first hears the word. Meanwhile the
reader is not actually missing anything at 08:59: the base word and the rule were both taught early,
which is the entire point of the culling.

So the last few percent of any stretch are scattered the length of the deck, and they measure the
cull rather than the passage. The median behaves: deck positions track first occurrence closely
(median sentence index rises monotonically through every thousand-card band of the deck), and so
does everything up to about the 95th percentile. Hence:

- **the headline is the share**, `COVER = 0.95` by default, computed as the position of the
  ⌈0.95·n⌉-th nearest card among the words met so far;
- **the furthest card is kept beside it**, in its own column, so nothing is hidden and `--cover 1`
  makes the two columns agree;
- 95% is also where the reading-comprehension literature puts the threshold for following a text
  unaided, which is the nearest thing to a principled number available here. It is a flag because it
  is a judgement.

## Words the deck does not teach

The `no card` column counts glosses of the file that no card in the deck teaches — 194 of 6,528 on
the Russian deck, about 3%. Four ways one gets there, and only the last is the deck being wrong:
every occurrence of a form was culled by the rules stage; `--previous` left it out as already
taught; the deck was built with a different set of stages (`--no-concepts`, `--no-rules`,
`--teach-script`); or the deck predates the word, having been built from an earlier cut of the file.

They are counted in the denominator and can never be reached, so a stretch with more of them than
the share leaves over has no answer at all and the row says `--` rather than a number. Reporting
them is the honest move: a gap is a card the reader will not be shown, not necessarily a word they
cannot follow.

## How the clock gets back in

`subtitles.text_of` throws timing away, which is the right thing for every other stage. So:

- `subtitles.timed` runs the same fold and returns each cue's **offset into the text that fold
  produced**. The two share `_folded`, one list of pieces, so the text cannot drift from the
  offsets: the text is the pieces joined and the offsets are their lengths summed. Checked against
  the 599 KB Russian file — 7,229 cues, every offset landing exactly on its cue's text.
- `SentenceTerms.start` carries the parser's character offset for each sentence (`-1` when the
  tokenizer offers none).
- `Gloss.first_sentence` records which sentence a gloss was made for. A gloss is made once, at its
  first occurrence, so this is where the reader first meets it — and for a concept or a rule, the
  first sentence that needed it, since the builder holds the sentence being walked and every gloss
  made under it takes that.
- A sentence is timed by the cue it *starts* in, which is when the viewer first hears its words. A
  sentence the parser gave no offset for, and anything before the first cue, is timed at zero rather
  than dropped.
- `anki.placed` reads the cards back out of the package: which gloss each teaches (the key tag),
  which side it is (the kind tag), and how far in it sits.

The deck is read rather than recomputed because shuffling has no seed by default — a rebuild is a
different order, and only the file the reader has can say which one theirs is. Recognition cards
alone are consulted: producing a word from its meaning is a further skill, not one that following a
subtitle asks for.

## A deck exported from Anki mid-study

The more useful input, and the more awkward one. A deck decker wrote is entirely unstudied and its
due numbers are the positions deck building gave them. A card that has been studied carries a due
number that is a day, not a position, so the two cannot share a scale. They do not have to: a
studied card costs its reader nothing further, so `anki.placed` marks those and ranks only the rest
among themselves, and a gloss already behind the reader answers position zero. Export the deck from
Anki, point `--deck` at the export, and the table says how much is left rather than how much there
was.

Suspended cards are not modelled — a suspended new card will never arrive but is still counted as
one to study. Nothing in the run reveals it, so it is named here rather than guessed at.

## What it costs

The stage re-runs extraction and definition over the subtitle file, because a card's gloss key is a
hash of its inflected form and Wiktionary's own definition, and nothing short of the definitions
reproduces it. With pages cached that is the parse plus the glossing: **2m15s** for the 6h38m
Russian file (184k characters, 6,158 sentences, 6,528 glosses) on this machine, of which 99 seconds
is Stanza. Without its model it waits for the host as every run does, and a timeline
run should be given the same stage flags the deck was built with or the gap count will be noise.

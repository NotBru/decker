# What a run says while it runs

> The documents in `docs/instructions/` are the design and outrank this one. This records the
> choices taken while building the thing that prints.

A run of decker over a series is an hour of one process doing four long things in sequence, and
until `decker/console.py` existed it said almost nothing about which. Every stage printed to stderr
directly: a few hundred lines, all the same colour, with the two that mattered — what could not be
fetched, what was skipped — somewhere in the middle of them. Nothing said how far along anything
was, and the longest silences were the ones before any output at all.

## Levels

Four, set by `-v`/`-q` and nothing else:

| Level | Flag | What it keeps |
| --- | --- | --- |
| `QUIET` | `-q` | What the run could not continue past, and the Ctrl+C notice. |
| `NORMAL` | — | The shape of the run: one line per stage, the counts, the warnings. |
| `VERBOSE` | `-v` | Every word, and what became of it. |
| `DETAIL` | `-vv` | Every fetch, every model call and how long it took. |

`NORMAL` is what every example in these documents shows, and it is deliberately short: a sentence
per stage, so a finished run reads as a summary rather than a log. `-v` is the level to watch a long
run at; `-vv` is the level to debug one at, and it is loud — a model call per word, timed.

## A colour per kind, and four of them per outcome

Levels get colours because a warning has to be findable in a wall of detail: errors red, warnings
yellow, headings bold, detail dim.

The four added later are not levels but **outcomes**, and they exist because `-v` was useless
without them. A thousand dim lines all alike say a word was looked up, and nothing about whether it
became a card — which is the only question worth asking of a run in progress.

| Kind | Colour | What it means |
| --- | --- | --- |
| `found` | green | The word has an entry, and here is what it cost the deck. |
| `fixed` | cyan | The word had no entry and was rescued into one: a misspelling corrected, a foreign word explained by the model. |
| `missing` | dim yellow | Wiktionary has no entry, and nothing recovered it. |
| `dropped` | dim magenta | Thrown away on purpose: a number, a word the model called unrecognizable, a foreign word the learner already knows. |

Scanning a run for magenta and finding a real word in it is how a bad drop rule gets noticed, which
is the whole reason the drops are *named* and not merely counted. `[decker] dropped as numbers: 3,
1758` is the only place `terms._is_number` is ever visible; a token listed there that is not a
number is a bug and nothing else would report it.

A word with an entry that ends up adding nothing — every sense already taught, every instance culled
by the rules stage — prints `nothing new to teach` in the drop colour, because otherwise it looks
exactly like a word that was never reached.

## The bar

One line at the bottom, redrawn after every log line, so the log scrolls above it and it stays put.
Cyan, because none of the log kinds are.

**Its units are the phase's own, and it never shows them.** Glossing counts characters of source
text, the title scan counts compressed bytes of the dump, the download counts bytes off the socket,
card building counts glosses. A number whose unit changes between phases explains nothing to the
person reading it, so the bar shows a share and a name and no count. Characters of source are also
the honest unit for glossing: sentences are not equal work, and a bar that jumps by a percent on a
one-word line of dialogue and stalls on a paragraph is worse than no bar.

The phases, in the order a full run meets them:

| Phase | Counts | Skippable |
| --- | --- | --- |
| `dump` | bytes of the title dump, off the socket | no — half a dump is not a dump |
| `index` | compressed bytes of the dump, scanned | no |
| `titles` | multi-word titles parsed | yes |
| `terms` | characters of source, extracted | yes |
| `glossing` | characters of source, glossed | yes |
| `cards` | glosses translated | yes |

`index` cannot ask the decompressor where it is without paying for it every line, so it advances by
a fixed step every 50,000 titles against a titles-per-compressed-byte constant. The share it shows
is a few percent out at worst, which is all a bar is for.

None of this happens when stderr is not a terminal, or when `NO_COLOR` is set: a redirected run
writes plain lines in order, which is what a file or a pipe wants, and what every measurement in
these documents was taken from.

## Ctrl+C ends the phase

A skippable phase installs a SIGINT handler that sets a flag; the loop inside asks `console.skipping()`
and breaks, and what the phase had done by then stands. A run is a sequence of stages that each
degrade gracefully — glossing fewer words, parsing fewer titles, translating nothing — and being
unable to say "enough of this one" without losing the hour behind it is what made long runs
unusable. A second Ctrl+C raises `KeyboardInterrupt` as normal, because the first must not take that
away.

Interrupting `titles` costs only the titles not reached: each one is written to the cache file as it
is parsed, so the next run starts where this one stopped. Interrupting `glossing` keeps every gloss
made so far and builds the deck from them. Interrupting `cards` turns the translator off for the
rest of the run rather than stopping it — a card that keeps the edition's language is what a run
without a model produces anyway, and the translator's report says how many did.

## The silences that are left

Three stretches used to print nothing at all, and each now says what it is doing and how long it
took:

- **Loading Stanza.** Four models off disk is a quiet ten to twenty seconds, and a first run for a
  language downloads them, which is minutes of a terminal that looks hung. `loading the Russian
  parser (tokenize,pos,lemma,depparse)` before, `parser ready in 4.8s` after.
- **Parsing the document.** One call over the whole text that cannot report its way through, so the
  only honest thing is to say it has started and how much it was given.
- **Scanning the dump.** Nine million titles off a gzipped file, which is twenty seconds of nothing.
  It has a bar now, and the line above it names the file — a run silently re-downloading the dump
  and a run reading a cached one looked identical from outside.

Model calls are timed at `-vv`, and a remembered answer says so rather than being silent, because
the difference between a cold run and a warm one is the entire difference in wall clock and it
should not have to be inferred from the clock.

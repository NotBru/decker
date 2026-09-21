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

**A line about a word says which word separately from what happened to it.** `log()` takes the word
as `word=`, and the two places a line is shown lay it out their own way: a redirected run writes
`[decker] 'servilleta': 2 glosses`, and the screen gives the word a column of its own next to the
time. Before this the word was written into the middle of each message, in a different position in
each of them — `no es entry for 'x'`, `'x' is foreign and widely known` — which is unreadable as a
column and was the one thing every one of those lines had in common. The messages lost the word and
the `[decker]` prefix; nothing else about them moved.

One recolouring came with it: a foreign word taught with the model's own explanation was logged as
detail, dim, while the *native* word taught the same way was logged as `fixed`. Both are a word with
no entry rescued into a card, which is what `fixed` means, and only one of them was counted as one.

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

The bar still shows no count and no unit. The dashboard below does, because it has a line to say
what it is counting on — `characters 1,635 left` under a phase named `glossing` is a different
thing from a bare number beside a bar, and the objection above was never to the number.

**It does show a time**, at the right-hand end: how long the phase has left at the rate it has run
so far, or — before there is a rate to say that from — how long it has been going. A share on its
own is a still picture. A phase waiting on a host that will not answer holds the same percentage for
as long as it waits, and the only thing on the terminal that can tell that apart from a run that has
died is a number that moves. This is the same pair the screen's own bar has always shown; the plain
bar was the one without it.

None of this happens when stderr is not a terminal, or when `NO_COLOR` is set: a redirected run
writes plain lines in order, which is what a file or a pipe wants, and what every measurement in
these documents was taken from.

## The screen

A bar says how far along a run is and nothing about what it is making. At `-v` the log says what
became of each word and scrolls past faster than anyone adds up; at the default it says almost
nothing, and the shape of the deck appears in the summary at the end, by which time the hour is
spent. Both are the same missing thing, and `decker/screen.py` is the answer to it: when stderr is a
terminal, a run draws on it instead of printing lines.

```
 decker · es → en · qwen3.5:4b · flamencos                                            34s
[15:40:01] pescuezo: 2 senses from https://en.wiktionary.org  │ RUN
[15:40:01] pescuezo: 1 gloss                                  │ elapsed              34s
[15:40:01] collar: 2 senses from https://en.wiktionary.org    │ phase           glossing
[15:40:01] collar: 1 gloss                                    │ left               1m00s
[15:40:01] bananas: 1 sense from https://en.wiktionary.org    │ characters    1,635 left
[15:40:01] bananas: 2 glosses                                 │   of                4/12
[15:40:01] y: nothing new to teach                            │
[15:40:01] fumaban: 1 sense from https://en.wiktionary.org    │ CARDS
[15:40:01] fumaban: 2 glosses                                 │ built                 46
 glossing ███████████████░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░  29%  1m00s left
```

curses, and the standard library's: the panes, the colours and the bar are three things a terminal
does, and a dependency for them would be a dependency in the pipeline's `pyproject.toml` for the
sake of the console.

**The log is the same log.** Same lines, same levels, same four outcome colours; `-v` is still the
level to watch a run at and `-vv` still the level to debug one at. What the pane adds is the time
and the word, in two columns, so a thousand lines have a shape: a run whose left edge has gone
yellow is a run that has lost its mirror, and it says so in the first screenful rather than in the
counts at the end.

**The dashboard is the running answer to what the deck will be**, in the order the questions
actually arrive:

| Section | What it answers |
| --- | --- |
| `RUN` | Elapsed, the phase, an estimate of what is left of it, and the phase's own count — *characters*, *titles*, *glosses* — beside the sentences it works out to. |
| `CARDS` | How many cards exist, split into recognition and production. |
| `GLOSSES` | How many, split into words, concepts, rules, symbols and foreign words, with the ones a previous deck already teaches counted separately. |
| `WORDS` | The four outcomes, added up: found, rescued, no entry, dropped. |
| `COST` | Pages fetched against pages read from the cache, model calls against answers remembered, and the seconds the model has actually taken. |

The counts are not summaries computed at the end and shown early. Each is incremented at the one
place the thing comes into being — a gloss appended, a card paired, a payload read or fetched, an
answer asked for or remembered — which is the only way a number can be true while the run is still
going. The outcome tallies are counted *before* the level filter, so they are the same at every
verbosity: at the default not one of those lines is printed, and the tally is the only place the run
says how many words it rescued or threw away.

`COST` is the one a person reads with a decision in mind. `model asked 0, remembered 81` is a warm
run and will finish in a minute; the same line with the numbers the other way round is the hour.
Until now that difference could only be inferred from the clock.

### The two descriptors, and the frame that tore

The screen borrows both of the run's own descriptors for the duration, for two different reasons.

**stdout**, because curses draws on fd 1 and cannot be told otherwise, and fd 1 is where `decker deck
--format text > cards.txt` sends the deck. Drawing the screen into that file and printing the cards
onto the screen are the two ways of getting this wrong. So fd 1 is pointed at stderr's terminal
while the screen is up, what the run writes to stdout is held, and it is let go once the screen is
down — after the log, because the cards are the product and should be the last thing on the terminal
rather than buried above the log that built them.

**stderr**, because it is not only decker's. Every line decker writes goes through the console, but
stanza logs through `logging`, urllib warns, and a Python warning arrives whenever it arrives:

```
2026-09-16 15:40:25 WARNING: Language es package default expects mwt, which has been added
```

One line like that scrolls the terminal up by a row, and from that moment curses is drawing against
a picture of the screen that is off by one. It does not recover: the frame tears and stays torn for
the rest of the run, mixing rows from two layouts —

```
│ droppedetched              4
│ model fetchedred          15
```

— which is what the first version of this file did, and what took the longest to understand,
because the *virtual* window curses holds was correct in every frame. So fd 2 becomes a pipe, and
what comes out of it is put into the log like any other line, dim and with no word, and replayed
with the rest on the way out. A stanza warning is exactly the kind of thing a person goes looking
for afterwards.

The pipe is drained by a thread and not between redraws. A pipe nobody is reading fills after
sixty-odd kilobytes and then blocks its writer, and the writer is the run: stanza downloading a
model writes a progress bar for minutes inside a single call that redraws nothing, which is exactly
the shape that would have hung. A frame that arrives after somebody else's line is painted in full
rather than diffed, which repairs a screen that was scrolled before the pipe was in place.

### What the terminal is left holding

The log is replayed as ordinary lines when the screen comes down, followed by the dashboard's own
rows, and the terminal's scrollback — which is the thing a person actually searches — ends up
holding what a plain run would have left it. A screen that simply vanished would take the run with
it: the word that could not be fetched, the sense that was dropped, the warning in the middle of an
hour.

It is bounded at 20,000 lines, because the alternative is holding a series' worth of strings for an
hour in order to print them once. A run that overflows it says so, in the warning colour, at the top
of the replay, and `--no-screen` is the flag for a run whose whole log matters.

### A frame every half second, whoever asked for it

Every redraw used to be caused by the run saying something: a log line, or a step of the bar. That
is the right trigger for a run that is talking and the wrong one for a run that is not, and the
stages that say nothing are exactly the ones whose progress a reader wants — the parse of a
megabyte, a page fetched from a mirror that is not answering, a model behind a tunnel that is down.
The screen froze with them, clock and all, and a frozen screen and a dead run look the same.

It was worse than showing the last thing that happened: it showed the one before. A redraw within a
fiftieth of a second of the previous one is dropped, because at `-v` the log moves faster than a
terminal can paint and the next redraw was always coming. When nothing followed, the dropped frame
was the final state of the screen. Two lines logged in the same breath — `parser ready in 54.5s` and
`parsing 120000 characters` — are one redraw and the second line is the one held back, so a run that
stalled in the parse sat there claiming to have stalled in the loader. That is how a dead
`DECKER_WIKTIONARY_HOST` tunnel was read, on 2026-09-19, as a hung Stanza.

So there is a thread that asks for a redraw twice a second and draws nothing of its own. Everything
on the screen is read from the console at draw time, so a beat during a silent stage picks up the
elapsed time, the phase's estimate, and whatever the stderr listener has caught since; a beat during
a stage that is talking meets the throttle above and costs nothing. Two threads now ask curses for a
frame, so redraws are taken under a lock — curses is not reentrant, and two `doupdate`s interleaved
paint a frame made of halves of two. The beat is stopped and joined before `endwin`, because a frame
landing after the terminal has been given back is half a dashboard printed over the run's own
output.

Half a second is the interval: slow enough to cost nothing next to the run's own work, fast enough
that the elapsed time reads as a clock rather than a stutter. It bounds how stale the screen can be,
which is the number that matters — no frame is ever older than half a second, whatever the run is
doing.

The run without a screen has the same thread, pulsing the one-line bar, for the same reason. It
draws only during a phase: between phases the plain path has never drawn anything, and a heartbeat
is not a reason to start.

### When there is no screen

`--no-screen` asks for the old behaviour, and it is also what a run gets without asking when stderr
is not a terminal, when `NO_COLOR` is set, at `--quiet`, when `TERM` is unset, when the terminal is
smaller than 60×10, or when curses will not start for any other reason — the exception is caught and
the run carries on with plain lines. Below 76 columns the dashboard is dropped and the log takes the
whole width; a two-column layout that leaves fifteen columns for the log is worse at the thing the
log is for than one column is.

Two things about the plain path have changed since, and only for a terminal: its bar carries the
time described above, and it is redrawn on the same heartbeat rather than only when a line is
logged. A redirected run is untouched — it has no bar at all — so every measurement in these
documents still comes from a run writing the same lines in the same order.

## Ctrl+C ends the phase

A skippable phase installs a SIGINT handler that sets a flag; the loop inside asks `console.skipping()`
and breaks, and what the phase had done by then stands. A run is a sequence of stages that each
degrade gracefully — glossing fewer words, parsing fewer titles, translating nothing — and being
unable to say "enough of this one" without losing the hour behind it is what made long runs
unusable. A second Ctrl+C raises `KeyboardInterrupt` as normal, because the first must not take that
away.

None of that changed under the screen: curses is started with `cbreak` and never `raw`, so the
terminal still turns `Ctrl+C` into a signal, and ending the phase with it remains the one
interaction a run has. The screen also reads no keys at all unless stdin is a terminal — the source
text can arrive on stdin, and a screen polling the keyboard would be eating the document.

Interrupting `titles` costs only the titles not reached: each one is written to the cache file as it
is parsed, so the next run starts where this one stopped. Interrupting `glossing` keeps every gloss
made so far and builds the deck from them. Interrupting `cards` turns the translator off for the
rest of the run rather than stopping it — a card that keeps the edition's language is what a run
without a model produces anyway, and the translator's report says how many did.

## `--limit-glosses`, which is Ctrl+C on a count

Bru asked for it on 2026-09-21: a way to stop the glossing stage early without sitting over the
run. It is the same ending `Ctrl+C` reaches — the walk over the sentences breaks, what is glossed is
glossed, and the run carries on to build a full deck from it — reached on a number rather than on a
key. Everything after it is the ordinary pipeline: the cards are built, the deck is shuffled, the
package is written, and the deck is a real deck of the opening of the text.

- **Checked between terms, not between glosses.** A term's glosses are made together: its senses,
  the characters it is written in, the terms its etymology decomposes it into. Cutting at an exact
  count would cut inside one of those, so the count is asked after each term and the list
  overshoots — 18 glosses for `--limit-glosses 10` on a Japanese sentence with disambiguation off,
  where one term brought eight senses. The flag is a floor, and the run says where it actually
  stopped:

  ```
  [decker] stopped at 18 glosses (--limit-glosses 10); the deck is built from these,
           1 of the source's 2 sentences read
  ```

  At `warn`, because a deck built from part of a text looks exactly like a deck built from all of
  it and the difference is the whole point of the flag.

- **It is the glossing stage's limit and no other's.** Extraction still reads the whole source and
  the title index is still built for it: those are the cheap stages, and stopping them early would
  make the run's own numbers — how many terms the text has — a lie about the text.

What it is for is the same thing the interrupt is for: seeing what a deck of this source is going to
look like before paying for the whole of it. `--preview-after`, which would have written a deck
mid-run and carried on, was considered and dropped on the same day; this is the cheaper half of it,
and the run that wants a full deck afterwards simply runs again without the flag — the pages, the
model's answers and the audio are all cached by then.

## The silences that are left

Three stretches used to print nothing at all, and each now says what it is doing and how long it
took:

- **Loading Stanza.** Four models off disk is a quiet ten to twenty seconds, and a first run for a
  language downloads them, which is minutes of a terminal that looks hung. `loading the Russian
  parser (tokenize,pos,lemma,depparse)` before, `parser ready in 4.8s` after.
- **Parsing the document.** One call over the whole text that cannot report its way through, so the
  only honest thing is to say it has started and how much it was given. It is still the longest
  stretch with no share to show; what it has now is a clock that keeps moving, which is the
  difference between a stage that is slow and a run that has died.
- **Scanning the dump.** Nine million titles off a gzipped file, which is twenty seconds of nothing.
  It has a bar now, and the line above it names the file — a run silently re-downloading the dump
  and a run reading a cached one looked identical from outside.

Model calls are timed at `-vv`, and a remembered answer says so rather than being silent, because
the difference between a cold run and a warm one is the entire difference in wall clock and it
should not have to be inferred from the clock.

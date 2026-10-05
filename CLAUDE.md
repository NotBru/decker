# Working in this repo

## Who writes which documents

`docs/instructions/` is written by humans only. Never create, edit or extend anything there. It is
the design's source of truth and is kept at a deliberate, conscious rhythm — an agent writing it
defeats that. If the design itself needs to change, say so in your reply and let the human write it.

`README.md` was the same until 2026-09-15, when Bru asked for it to be updated directly. Treat it as
the human's prose still: change it when told to, keep to its own register, and edit the lines that
are wrong rather than rewriting around them. Flags, defaults and what a source file may be are the
things that go stale there — the model default alone changed twice in two days.

`docs/execution/` is yours. Design and implementation choices taken while building go there, one
document per topic, each one saying up front that the human docs outrank it. Keep them current as
the code changes.

- [Term extraction](docs/execution/term-extraction.md) — v1's choices about titles, matching and
  gaps.
- [Definition fetching](docs/execution/definition-fetching.md) — where the data comes from, how
  glosses and their dependencies are made, and sense disambiguation.
- [Deck building](docs/execution/deck-building.md) — cards, translation, shuffling and the Anki
  package.
- [Concept identification](docs/execution/concept-identification.md) — cards for the grammatical
  terminology a definition uses: what counts as a concept, how the glossary is read, and what it
  costs.
- [A local Wiktionary](docs/execution/local-wiktionary.md) — a full offline mirror: why, how it was
  built and how to bring it back up, the settings that had to be right, and what it still cannot
  give.
- [Model backends](docs/execution/model-backends.md) — ollama, an OpenAI-compatible endpoint and
  Anthropic behind one interface: why the model is not a vendor commitment, what it costs in
  privacy, and which models have been measured.
- [Morphological rules](docs/execution/morphological-rules.md) — the regularity behind an inflected
  form, learned once: what a feature bundle is, when a rule is written and when its card appears,
  and what the stage costs.
- [Detecting a form-of](docs/execution/form-of-detection.md) — the two regexes that decide what
  points at what: how precise they are, what widening them costs, and the markup that would do it
  properly.
- [The terms a word is made of](docs/execution/etymological-components.md) — the sums an etymology
  states, glossed recursively: why the plus is the whole test, what the looser rule would have
  carded, and what the stage costs per language.
- [Deck growth](docs/execution/deck-growth.md) — what a deck costs as the corpus grows, measured over
  nine Spanish sources with concepts and rules on and off: the curves, and what they settle.
- [Words Wiktionary has no entry for](docs/execution/unknown-words.md) — misspellings looked up,
  foreign words explained or dropped, and the fabrications the first prompt produced.
- [The benchmark](docs/execution/benchmark.md) — 24 sentences, four languages, known answers: what
  sense disambiguation is checked against, and why the five-sentence one stopped discriminating.
- [Manga as a source](docs/execution/manga.md) — a mokuro `.mbz` archive read for its speech: why
  a block is the sentence and its lines are not, the reading order that came free, and the bubbles
  that are only punctuation.
- [Subtitles as a source](docs/execution/subtitles.md) — `.srt` and `.vtt` folded back into prose:
  the rolling repeats, the markup, and where sentence boundaries come from when a machine wrote the
  captions and left no punctuation.
- [What a run says while it runs](docs/execution/the-console.md) — levels, the colour per outcome,
  the bar and its units, and what Ctrl+C ends; and the curses screen a terminal gets — log to the
  left, the deck's tally to the right — including why it takes both descriptors and what it leaves
  behind.
- [Teaching the script](docs/execution/teaching-the-script.md) — the default-off flag that teaches
  the characters a term is written in: why the test is a script and not an alphabet, where a symbol
  card's text comes from, and what it costs in each kind of writing system.
- [When can I watch this](docs/execution/timeline.md) — a deck read back against the subtitle file
  it was built from: what the clock costs in cards, why the headline is 95% of a stretch and not all
  of it, and what a deck exported mid-study changes.
- [When a remote stops answering](docs/execution/connectivity.md) — a dropped tunnel or a
  Wiktionary outage is waited out and logged, never turned into a degraded deck: what counts as
  unreachable, what still degrades, and what a wait costs.
- [Ten languages, one mother tongue](docs/execution/language-survey.md) — the whole pipeline over ten
  languages for a speaker of English: what works everywhere, which stage gives way in each, and what
  was done about the first four findings.

## Committing

Commit when a piece of work is finished, not when asked: Claude's changes go in their own commit
with the co-author trailer, and a stage that is built and written up is committed before the
session ends.

## Running it

```
uv run decker --target-lang es source.txt              # the whole pipeline: writes source.apkg
uv run decker deck --target-lang es --format text source.txt   # the cards, in study order
uv run decker define --target-lang es --format markdown source.txt   # glosses, and stop there
uv run decker extract --target-lang es source.txt      # terms, sentence by sentence
uv run decker index --target-lang es                   # build the whole title index up front
uv run decker --target-lang es episode.vtt             # subtitles: .srt and .vtt read as prose
uv run decker --target-lang ja 0001.mbz.zip            # manga: a mokuro archive read for its speech
uv run decker timeline --target-lang es --deck episode.apkg episode.vtt   # the clock, in cards
```

With no subcommand the whole pipeline runs, which is what `deck` does; `define`, `extract` and
`index` stop it earlier. `timeline` is the one that reads rather than writes: given a cue file and a
deck built from it, it says how far into the deck a viewer must be to have met the words said up to
each timestamp — 95% of them by default, the last of them in a column beside it, and days at
`--rate` new cards a day. It re-runs extraction and definition over the file to recover the gloss
keys, so give it the stage flags the deck was built with.

A deck already in Anki is updated with one of two flags: `--previous deck.apkg` builds only what it
does not teach and numbers those cards after the ones it has not shown, while `--update deck.apkg`
rebuilds the whole deck keeping the identity its notes have there, so an import corrects the cards
already being studied instead of duplicating them. Both read the gloss key decker tags every note
with.

A source is plain text, a `.srt` or `.vtt` cue file, or a mokuro `.mbz` archive — the zip or the
folder it unpacks to. A manga's blocks are its sentences and a block's `lines` are the columns one
was set in, so the lines are joined and the blocks are not; the pages come in the order the
archive's metadata lists them, which is already reading order. The deck's title comes from that
metadata (`Gokurakugai 0001`) since the file is named after the volume number alone.

Sense disambiguation, and translation when `--mother-lang` is not `en`, need
an ollama host (`--ollama-host`, or `OLLAMA_HOST`); without one the run degrades and says so.
Stanza models, Wiktionary title dumps, parsed titles, fetched pages, model answers and audio are
cached under `~/.cache/decker` (`DECKER_CACHE_DIR` overrides).

The terminology a definition is written in — dative, diminutive, colloquial — becomes cards of its
own, one per `Appendix:Glossary` entry it links to, titled `Concept:` and carrying no production
pair. A link to a place on a language's own appendix counts too — `-taa`'s *causative verbs* is
`Appendix:Finnish verbal derivatives#Causative` — read through the mirror like any page and titled
with the appendix beside it. `--no-concepts` turns the stage off.

`--teach-script`, off unless asked for, adds the writing system itself: every character **of a term**
written in a script the mother tongue does not use becomes a `Symbol:` card, with a production pair
like a word's, ahead of every term that contains it. The term only — not the definition, the
examples or the readings — and scripts, not alphabets, so `ñ` and `ç` are Latin and cost nothing
while kana, kanji and Cyrillic each cost a pair of cards. A character whose language reads it
several ways carries the `Readings` list Wiktionary gives it instead of a pronunciation, and a
character the text also teaches as a word of its own is one card and not two — the word's, which
also replaces a shape glossed from Translingual.

`--limit-glosses N` stops glossing at N and builds the deck from what stands, which is Ctrl+C's
ending reached on a count; the check is between terms, so the count overshoots by the last term. Which scripts a reader reads is known for English only; another
`--mother-lang` turns the stage off with a line saying so. With neither flag given, a run whose
source is mostly written in a script the reader cannot read asks once before it starts, where there
is a terminal to ask on and the source did not come in on it; `--no-teach-script` answers in
advance, and a run that cannot be asked gets the same finding as a warning line.

Where an etymology states a sum of terms **in the language being taught** — `des- +‎ cargar`,
`veneno +‎ -oso` by surface analysis — each of those terms becomes a card of its own, ahead of the
word made of them and recursively, a component being a word that may be a sum itself. Only a sum,
so a doublet, a cognate and a `Compare` name nothing; only that language, so the foreign ancestors
stay prose on the card. `--no-components` turns the stage off.

The regularity behind an inflected form becomes a card too, titled `Rule:` and likewise without a
production pair: the model is asked whether a form obeys a rule already written for its feature
bundle and, failing that, whether it is regular at all. Instances are then culled — the first four,
then half as often every four shown — so a rule met all through a text costs a handful of cards
rather than one a paragraph, and the base word's card always stays. The rules themselves outlive the
run in `~/.cache/decker/rules/<lang>.json`, so the next text in that language starts with what the
last one worked out. `--no-rules` turns the stage off.

`--wiktionary-host` (or `DECKER_WIKTIONARY_HOST`) fetches pages from a Wiktionary mirror instead of
Wikimedia, if there is one to point at — building one is a day's work, written up in
[A local Wiktionary](docs/execution/local-wiktionary.md), with the config, router, drivers and
filter it needs under `tools/wiktionary/`. The wiki itself, its `LocalSettings.php` and the dumps
are not in this repository and never should be.

Pages cache by title whichever source answered, so a title read from a mirror is never fetched
from Wikimedia afterwards; the payload records which source it was, since a mirror carries
no audio and a run has to be able to say that. Cards built against one are silent. The title dump
still comes from `dumps.wikimedia.org`, once per edition.

`Appendix:Glossary` is read from the mirror when the mirror has it and from Wikimedia when it does
not, which keeps concept identification working for exactly the runs a mirror serves. A mirror has
it only if its namespaces were declared and `namespaceDupes.php` run — the dump carries the pages,
but an import with no `Appendix:` namespace files them under main — see
[A local Wiktionary](docs/execution/local-wiktionary.md). The Wikimedia fallback leaks nothing the
mirror exists to hide, the title being the same on every run and for every text; it is a live page
there, so its revision id is asked for each run and the page re-read only when that id has moved.
A mirror's copy is a dump's copy and is cached without a revision.

## Tests, and the one measurement that is not a test

v1 ships no unit tests, by decision recorded in `docs/instructions/v1/design.md` — "Do not test."
Nothing asserts on decker's own functions, and checking work still means running the pipeline ad hoc
from a scratchpad, on the smallest input that shows the thing.

What does live in the repository, at Bru's instruction on 2026-09-15, is
`tools/benchmark/` — 24 sentences in Spanish, German, Russian and Chinese with known answers for the
one stage whose output is a judgement rather than a computation:

```
OLLAMA_HOST=... DECKER_WIKTIONARY_HOST=... uv run python tools/benchmark/run.py gemma4:latest
```

It scores a *model*, not the code, which is why it is not the thing the design ruled out; see
[The benchmark](docs/execution/benchmark.md) for what it measures and what it found. If the design's
line should be rewritten to say so, that is the human's to write.

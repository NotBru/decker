# Working in this repo

## Who writes which documents

`docs/instructions/` and `README.md` are written by humans only. Never create, edit or extend
anything there. They are the design's source of truth and are kept at a deliberate, conscious
rhythm — an agent writing them defeats that. If the design itself needs to change, say so in your
reply and let the human write it.

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
- [Deck growth](docs/execution/deck-growth.md) — what a deck costs as the corpus grows, measured over
  nine Spanish sources with concepts and rules on and off: the curves, and what they settle.
- [Ten languages, one mother tongue](docs/execution/language-survey.md) — the whole pipeline over ten
  languages for a speaker of English: what works everywhere, which stage gives way in each, and what
  was done about the first four findings.

## Running it

```
uv run decker --target-lang es source.txt              # the whole pipeline: writes source.apkg
uv run decker deck --target-lang es --format text source.txt   # the cards, in study order
uv run decker define --target-lang es --format markdown source.txt   # glosses, and stop there
uv run decker extract --target-lang es source.txt      # terms, sentence by sentence
uv run decker index --target-lang es                   # build the whole title index up front
```

With no subcommand the whole pipeline runs, which is what `deck` does; `define`, `extract` and
`index` stop it earlier. Sense disambiguation, and translation when `--mother-lang` is not `en`, need
an ollama host (`--ollama-host`, or `OLLAMA_HOST`); without one the run degrades and says so.
Stanza models, Wiktionary title dumps, parsed titles, fetched pages, model answers and audio are
cached under `~/.cache/decker` (`DECKER_CACHE_DIR` overrides).

The terminology a definition is written in — dative, diminutive, colloquial — becomes cards of its
own, one per `Appendix:Glossary` entry it links to, titled `Concept:` and carrying no production
pair. `--no-concepts` turns the stage off.

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

## Tests

v1 ships none, by decision recorded in `docs/instructions/v1/design.md` — "Do not test." Check work
by running the pipeline ad hoc from a scratchpad, on the smallest input that shows the thing, not by
adding test files. The `docs/instructions/test-cases.md` this used to point at has been removed.

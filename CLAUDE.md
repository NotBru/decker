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
- [A local Wiktionary](docs/execution/local-wiktionary.md) — a full offline mirror: why, what it
  took, and what it still cannot give.

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
Stanza models, Wiktionary title dumps, parsed titles and fetched pages are cached under
`~/.cache/decker` (`DECKER_CACHE_DIR` overrides).

## Tests

v1 ships none, by decision recorded in `docs/instructions/v1-design.md`. Check work against
`docs/instructions/test-cases.md` by running the pipeline ad hoc from a scratchpad, not by adding
test files.

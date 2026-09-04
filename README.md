# Decker

This tool should take source material (text, audio, video, whatever), a target language that the
user wants to learn, their mother language, and construct an Anki deck that teaches, in the mother
language, the concepts required for the user to understand the parts of the source material that are
in the target language.

## Structure

### `docs/instructions/`

Everything inside this directory is intended to be written only by humans, so as to have a clear
ownership division. It also keeps human reasoning and decisions separate from AI.

### `docs/execution/`

This directory is intended to persist design choices/notes from AI agents. I don't read much of it
tbh.

### `docs/instructions/design.md`

This document should be the single source of truth for the design. Purposefully terse, so that a
human reader can get the gist of it quickly. Details may be offloaded to other documents, thus
making them part of the source of truth, but only as long as it's referenced by this document.

## Usage

Needs Python 3.13+, [uv](https://docs.astral.sh/uv/), and — for sense disambiguation, and for
translation into any mother language but English — an [ollama](https://ollama.com) host.

```
uv run decker --target-lang es --mother-lang de source.txt
```

That writes `source.apkg`, ready to import. The subcommands stop the pipeline earlier:

```
uv run decker extract --target-lang es source.txt   # terms, sentence by sentence
uv run decker define  --target-lang es source.txt   # glosses: definitions, examples, etymology
uv run decker deck    --target-lang es source.txt   # all of it, and the package (the default)
uv run decker index   --target-lang es              # build the title index up front
```

`source` may be `-` for standard input. `--format` chooses the output — `text` and `json`
everywhere, `markdown` for `define`, `apkg` for `deck` — and `--out` names the file.

### Languages

`--target-lang` is the language being learned, `--mother-lang` the one the cards are written
in; both are ISO 639 language codes — `es`, `de`, `pt`. A code decker cannot name is refused
before the run starts. The mother language defaults to `en`, which needs no translation and
never opens a connection.

### The model

Disambiguation and translation both ask a local model, named by `--model` or `$DECKER_MODEL`
(default `gemma4:latest`), on the host at `--ollama-host` or `$OLLAMA_HOST` (default
`http://localhost:11434`).

Without a reachable host a run does not fail. It keeps every sense, leaves the cards in
English, and says so — so read stderr before trusting a deck. It also reports any prose that
reached a card untranslated, and silence there means everything did:

```
[decker] 57 glosses
[decker] 4 fields kept their English: 4 definition echoed
[decker] 114 cards
```

`--no-disambiguate`, `--no-translate` and `--no-audio` skip those stages outright: much
faster, much worse.

### An offline Wiktionary

`--wiktionary-host`, or `$DECKER_WIKTIONARY_HOST`, points every page fetch at a mirror instead of
`<lang>.wiktionary.org`. Anything serving upstream's paths will do; a MediaWiki holding the
`pages-articles` dump answers `/w/api.php` and `/wiki/<title>` exactly as Wikimedia does.

```
uv run decker define --target-lang es --wiktionary-host http://localhost:8080 source.txt
```

For:

- **The fetched titles never leave the machine.** Every new word implies a Wiktionary query, in
  reading order, thus leaking information about the source text.
- **No rate limits, no 403.** Wikimedia's pacing and its backoff stop applying.
- **Nothing but the model's host is reached at run time**, once the title list is cached.

Against:

- **No audio.** Recordings live on Commons, `File:` pages are not in `pages-articles`, and the
  media is in no dump; a mirror offers no sound file and cards built against one are silent. A run
  says so once, since that is indistinguishable on a card from words that have no recording:

  ```
  [decker] no recordings offered by this source; cards will have no audio (a local Wiktionary carries none: media is in no dump)
  ```

- **The title list still comes from `dumps.wikimedia.org`.** One download per edition
  (`--edition`, `en` by default), reused by every run and every target language after it, so only
  the first run of all wants the network. It says nothing about what is being read.
- **A page fetched from the mirror stays silent.** Pages are cached by title alone, so a title read
  from the mirror is never fetched again — not by a later run against Wikimedia either, which is
  the point: extending a deck must not name the words already read to a source that has not seen
  them. The cost is that those cards keep no audio until `--refresh-pages` fetches them upstream,
  which does name them. A run says how many are in that state.
- **Roughly a day to stand up**, a few hours of it importing, and about 10 GB of database. What it
  took is in [docs/execution/local-wiktionary.md](docs/execution/local-wiktionary.md).

### Caching

Stanza models, Wiktionary title dumps, parsed titles, fetched pages and audio all cache under
`~/.cache/decker` (`DECKER_CACHE_DIR` overrides). The first run for a language downloads and
parses the entire title dump and is slow; the ones after it are not. `--refresh-titles` and
`--refresh-pages` go around the caches.

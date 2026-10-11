# Decker

Decker is a tool to AItomatically construct Anki decks for language learning. Specifically, it
constructs a deck with the minimum required words and concepts that you need to understand text,
audios, or generally media of your choosing.

You give it text in the language you want to learn, tell it your mother language and the target
language, and decker will construct the deck.

It uses Wiktionary for both definitions (along with IPA, examples, audio, etc) and concepts.

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

`source` may be a `.srt` or `.vtt` subtitle file as well as plain text: the cues are folded back
into prose, the rolling repeats of machine captions unrolled, and the `>>` a caption puts in front
of a new speaker dropped. Where such a file has no punctuation at all — some recognizers still
write none — the sentence boundaries come from the cue timings instead. It may also be `-` for
standard input, which is sniffed for cue files, since standard input has no extension to go by.

It may also be a manga: a [mokuro](https://github.com/kha-white/mokuro) archive, either the
`.mbz.zip` mokuro writes or the `.mbz` folder it unpacks to. Each speech bubble is one sentence, the
columns its text was set in joined back together, and the pages are read in the order the archive
lists them — which is already right to left, top to bottom. Bubbles that are only punctuation —
`⋯`, `‼︎！` — are dropped, and the pictures are never opened. The deck is named after the series and
volume the archive knows itself by (`Gokurakugai 0001`) rather than after the file, which is usually
just a number. See [docs/execution/manga.md](docs/execution/manga.md).

**Several sources** may be given at once, and they are read in order:

```
uv run decker --target-lang ru ep01.srt ep02.srt ep03.srt
```

Each is read by its own extension, so subtitles and plain text can be mixed, and a blank line is put
between them so that no sentence spans two — which is what `cat` gets wrong, running the last
sentence of one file into the first of the next. The deck is named after the first and says how many
followed (`ep01+2.apkg`, "ep01 and 2 more"), so building from three episodes cannot overwrite the
deck you built from one; `--out` and `--name` override both.

`--format` chooses the output — `text` and `json` everywhere, `markdown` for `define`, `apkg` for
`deck` — and `--out` names the file.

**A deck you are already studying** takes two flags, and they are different jobs. `--previous
deck.apkg` builds only what that deck does not teach, and numbers the cards after the ones it has
not shown you yet, so importing adds them to the end of the queue instead of among what is already
waiting. `--update deck.apkg` rebuilds the whole thing and keeps the identity its notes have in
Anki, so importing corrects the cards you have — their scheduling included — rather than putting a
second copy of each beside them; that is what to use when decker has learned to write a card
better, as it did when a production card stopped printing its own answer. Export the deck from
Anki to hand it back — with *Support older Anki versions* ticked, since decker cannot read the
compressed format newer Anki writes by default, and says so by name if you hand it one — or pass
the `.apkg` decker wrote. Both read the gloss keys decker records on every note, so a deck built
before those existed says so rather than quietly matching nothing. What an update cannot do is
move the cards you already have: they keep their place in the queue, so a card added ahead of one
you have already been given arrives behind it.

### Languages

`--target-lang` is the language being learned, `--mother-lang` the one the cards are written
in; both are ISO 639 language codes — `es`, `de`, `pt`. A code decker cannot name is refused
before the run starts. The mother language defaults to `en`, which needs no translation and
never opens a connection.

### The model

Disambiguation, the morphological rules and translation all ask a local model, named by `--model`
or `$DECKER_MODEL` (default `gemma4:latest`), on the host at `--ollama-host` or `$OLLAMA_HOST`
(default `http://localhost:11434`).

Without a reachable host a run does not fail. It keeps every sense, leaves the cards in
English, and says so — so read stderr before trusting a deck. It also reports any prose that
reached a card untranslated, and silence there means everything did:

```
[decker] 57 glosses
[decker] 4 fields kept their English: 4 definition echoed
[decker] 114 cards
```

`--no-disambiguate`, `--no-translate` and `--no-audio` skip those stages outright: much
faster, much worse. `--no-concepts`, `--no-rules` and `--no-components` switch off the three stages
that make cards of their own — the grammatical terminology a definition is written in, the
regularity behind an inflected form, and the terms an etymology decomposes a word into.

That last one reads the etymology the card already shows: where it states a sum of terms in the
language being taught — `descargar` is `des- +‎ cargar`, `venenoso` is `veneno +‎ -oso` by surface
analysis — each term gets a card of its own, ahead of the word made of them, and recursively, since
a term may be a sum itself. Only a sum, so a doublet or a `Compare` names nothing; only that
language, so the Latin an etymology walks back through stays prose on the card. See
[docs/execution/etymological-components.md](docs/execution/etymological-components.md).

`--teach-script` is off by default and adds cards rather than skipping them: every character of a
*term* written in a script the mother tongue does not use gets a pair of cards of its own, ahead of
the word that uses it — the letters of an alphabet, the kana and the kanji of a Japanese word, each
with what Wiktionary says about the character and how it is pronounced. Only the term: not its definition, its
examples or its transcription. The Latin alphabet counts as one, so a Spanish deck for an English
reader gains nothing and says so, a Russian one gains its alphabet, a Japanese one its kana and
its kanji. A character the text also teaches as a word of its own gets one card, not two: the word
card is the one kept, and where the shape was glossed from Translingual — `Kangxi radical #9` — the
word card replaces that too. A character card carries the readings Wiktionary lists for it — `Kan-on: けつ (ketsu)`,
`Kun: きまる (kimaru)` — where the language gives a character no single pronunciation, which is what
Japanese does; and a character the text also teaches as a word of its own gets one card, not two. Which
scripts a reader already reads is known for English only; under any other `--mother-lang` the flag
says so and stays off. With neither flag given, a run that finds its source mostly written in a
script the reader cannot read asks once, before it starts — on a terminal, with the source in a
file rather than on standard input; elsewhere it says in a line which flag would have taught them.
`--no-teach-script` is that answer given in advance. See
[docs/execution/teaching-the-script.md](docs/execution/teaching-the-script.md).

`--limit-glosses N` stops the glossing stage once N glosses stand and builds the deck from them,
which is what Ctrl+C does on a key. It is checked between terms, so the count overshoots by
whatever the last term brought, and the run says where it stopped and how much of the source it
read.

`--unknowns` decides what happens to a word Wiktionary has no entry for: `off` drops it, as decker
always did; `fix` (the default) looks the word up again when it is a misspelling, and teaches a
foreign word the reader would not know with a one-sentence explanation from the model; `all` also
teaches the foreign words they would know. Those cards say the model wrote them and link to no
entry, there being none — see
[docs/execution/unknown-words.md](docs/execution/unknown-words.md).

### Offline Wiktionary

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
- **Nothing but the model's host is reached at run time**, once the title list is cached —
  `Appendix:Glossary` and the language appendices, which the concept cards are made from, included,
  as long as the mirror
  carries the `Appendix:` namespace. A dump holds those pages but an import files them under the
  main namespace unless the namespaces were declared first; see
  [docs/execution/local-wiktionary.md](docs/execution/local-wiktionary.md). Where it does not,
  the glossary is read from Wikimedia and nothing else is.

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

Stanza models, Wiktionary title dumps, parsed titles, fetched pages, model answers and audio all
cache under `~/.cache/decker` (`DECKER_CACHE_DIR` overrides). The first run for a language
downloads and parses the entire title dump and is slow; the ones after it are not. A second run
over the same text asks the model nothing, the answers being kept. `--refresh-titles`,
`--refresh-pages` and `--refresh-answers` go around the caches.

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

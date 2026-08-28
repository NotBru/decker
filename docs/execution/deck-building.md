# Deck building: implementation choices

Written by an AI agent, not by hand. It records the choices taken while implementing the last three
stages of v1 — deck construction, shuffling and Anki output — which refine [the v1
design](../instructions/v1-design.md) without changing its shape. The design documents remain the
source of truth: where one of these contradicts them, the design wins and the code is wrong.

## Cards

- The two faces are dataclasses of their own (`Side`), carrying only the pieces the design puts on
  that face, so a card is the design's two bullet lists rather than a bag of fields a renderer picks
  from. The Anki templates then only have to lay out what is there.

- The production card depends on its recognition card and on nothing else. Whatever the gloss
  depends on is already behind that recognition card, and the ordering the design asks for is
  transitive, so naming the rest again would only be a second way to say the same thing.

- A gloss's dependency becomes the *recognition* card of the gloss it depends on, not its production
  card. What `patita` needs from `pata` is that the reader have met the word; being able to produce
  `pata` from its meaning is a further skill, and waiting for it would hold `patita` back for no
  reason the definition gives.

- The sound file rides on the recognition card's answer, next to the IPA. This is a small widening
  of the design, whose answer list names etymology, IPA and definition: the reading and the
  recording answer the same question, and v1 downloads the file already, so leaving it out of the
  deck would mean fetching audio the learner never hears. If the design meant the list to be
  exhaustive, this is the line to cut.

## Translation

- v1's mother language *is* the edition's, so the ordinary run translates nothing and never opens a
  connection: `Translator.needed` is false whenever `--mother-lang` is English, and the stage costs
  the run nothing at all.

- `--mother-lang` names a language as a word — `Spanish`, not `es` — because the name goes into a
  prompt rather than into an API. It is the same reason page fetching takes the language's name from
  the payload instead of keeping a table: nowhere in decker is there a code-to-name map to fall out
  of date.

- One call per gloss, carrying the definition, the examples and the etymology together, cached by
  the text asked about. A sense met by two terms is one call, and the three pieces of one gloss
  never disagree about how a word was rendered.

- The examples come back one for one or not at all. An example is a sentence and its rendering, so a
  model that drops or merges one has changed which sentence teaches what; a card quoting an
  untranslated right sentence is better than one quoting a translated wrong sentence.

- The prompt asks for the target language to be left alone — the example sentences, the headword,
  the forms a definition names — since those are the thing being taught and not prose about it.

- Failure is the same degraded run disambiguation has: warn once, keep what Wiktionary wrote. A deck
  in the wrong language is worth more than no deck.

## The shared ollama session

- Both stages that ask a model anything now go through `decker/ollama.py`: the host and its default,
  the prompt-under-a-schema call, reasoning turned off, and one warning per run naming which stage
  lost its model and what happened instead. Disambiguation moved onto it unchanged, which is what
  made translation a couple of dozen lines rather than a second copy of all of that.

## Shuffling

- The sort keys of a window are that window's own positions, permuted. Sorting by them can therefore
  move a card around inside its week and nowhere else, which is the design's window without any
  arithmetic about where a card is allowed to land.

- The topological sort is Kahn's algorithm over a heap keyed by those shuffled positions: at every
  step the ready card with the smallest key. That is what makes it *stable* in the shuffled order —
  a card waits exactly as long as its dependencies make it wait, and not one place longer.

- A dependency can still carry a card a little past the end of its window, when what it waits for
  lands late in the same window. Ordering wins over the window on purpose: a card whose dependency
  the reader has not met yet teaches nothing, while a card a few places into the next week is only
  slightly out of place. Over 400 cards with the design's window of 140, the furthest a card moved
  was 135.

- The seed is a parameter (`--seed`), so a deck can be rebuilt exactly. Without one the shuffle is
  fresh each run, which is what a first build wants.

## Anki output

- `genanki` is a dependency now. Writing an `.apkg` by hand means embedding Anki's collection schema
  and keeping it in step with Anki, which is a bigger commitment than the library.

- One note per card, not one note carrying both templates. Anki's new-card order is a property of
  the note, and shuffling routinely puts a production card far from the recognition card it depends
  on, so the pair has to be able to hold two different positions. Each note's `due` is its place in
  the shuffled order, which is how the order survives the import.

- Deck and model ids are derived from their names by hash rather than drawn at random as genanki
  suggests, and a note's GUID is the card's kind plus the design's identity for its gloss — the term
  and the sense. Building the same deck twice therefore updates the notes instead of doubling them,
  which is what a source text that has been edited slightly wants.

- The CC BY-SA credit sits both in the deck's description and on the back of every card, linking to
  the entry the text came from. This is the line [definition
  fetching](definition-fetching.md#licensing) said deck construction would have to find a place for:
  a document is read whole and a deck is read one card at a time, so the deck's own description is
  not enough on its own.

- Sound files travel in the package and are referenced the way Anki references media, by bare file
  name.

## What was checked, and what was not

- The three stages were run over the pages already in the cache — 26 real glosses, 52 cards, a
  package Anki's own schema reads back with its due numbers in order, its media listed, and its
  dependencies all ahead of what needs them. The window bound was measured on 400 synthetic cards.

- No model was reachable while this was written, so the translation prompt has never been answered
  by a live one: what is tested is that a mother language of English asks nothing, and that an
  unreachable host leaves the cards in English with one warning. The disambiguation refactor is in
  the same position — the degraded path is exercised, the answering path is not. Both want a run
  against the GPU box before the deck is trusted.

## Known gaps

- Every card lands in one deck with no subdecks, tags beyond `recognition`/`production`, or
  scheduling presets. The design says to dump a deck, and the order is carried by `due`, so anything
  further is the learner's to set up in Anki.

- The examples on a recognition card are the ones Wiktionary happens to give the sense, which for
  many senses is none. Nothing generates them.

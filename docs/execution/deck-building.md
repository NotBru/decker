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

- `--mother-lang` takes a code — `pt`, not `Portuguese` — because `--target-lang` does, and a caller
  should not have to remember which flag wants which shape. The word the prompt needs is made below
  the flag, in `decker/languages.py`, from the table Stanza already ships (`lcode2lang`, four
  hundred codes): a dependency decker already has, so there is still no map here to fall out of
  date, and still nothing fetched. An unknown code is refused while the flags are read rather than
  reaching the model as itself — cards written for "a speaker of pt-" are worse than a run that
  never starts.

- The comparison that decides whether to translate at all is made on codes, not on names, so
  `--mother-lang en` and an unset flag are the same run. Names appear at one point only: the prompt.

- The translated examples come back with the prompt's own list markers still on them —
  `- Mi tío es…` — from a model small enough to copy the bullet along with the sentence: qwen3:1.7b
  does it on every call. The marker belongs to the prompt, not the sentence, so it is stripped off
  again before the sentence reaches a card.

- One call per gloss, carrying the definition, the examples and the etymology together, cached by
  the text asked about. A sense met by two terms is one call, and the three pieces of one gloss
  never disagree about how a word was rendered.

- An example is carried as a pair — `pages.Example`, the sentence and the edition's rendering of it
  — and never as one string the translator cuts back up. The halves answer to opposite rules: the
  sentence is the target language and is the very thing the card teaches, the rendering is the
  prose and is the only half a model may touch. Only the rendering is sent, so no answer can rewrite
  a sentence. Joining them first and splitting on the em dash looked equivalent and was not: the
  separator occurs *inside* sentences too — eight of the 4,529 examples in a warm cache, among them
  `¿Te das? — Me doy. — Do you surrender? — I surrender.` — and each of those sent Spanish to the
  model and put the answer back on the card. Splitting from either end fails on a different one of
  them; keeping the halves apart fails on none. The separator is now only ever written, by
  `Example.__str__`, where the two are shown together. Three of the four outputs are unchanged by
  this — the deck, the Markdown and the terminal all render the pair through that one method — and
  the fourth, `--format json`, now carries `{"sentence": …, "rendering": …}` where it carried one
  joined string, which is the shape the data was always in.

- The examples come back one for one or not at all. A model that drops or merges one has changed
  which sentence teaches what; a card quoting an untranslated right sentence is better than one
  quoting a translated wrong sentence.

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

- The translation prompt has now been answered by a live model: three sentences of `barbapedro.txt`
  into German, `gemma4:latest` on the GPU box, 57 glosses and 114 cards with no warning raised, so
  every call was answered. The pair invariant held on all 41 examples that carry a rendering — every
  sentence reached its card in Spanish, every rendering came back German. The final run, with the
  schema requiring both fields, reported `4 fields kept their English: 4 definition echoed` — no
  etymology failures at all, where the first run left sixteen, and no examples refused. The package
  it wrote carries 41 media files over 114 notes, six of which hold more than one recording; `el`'s
  card plays both its Spain and its Colombia file.

- Two things the tally cannot do, both worth knowing before trusting the number. It cannot tell a
  lazy echo from a translation that is legitimately the same string — a loanword, a proper noun, a
  definition that is one word shared by both languages — so a count of echoes is an upper bound.
  And it counts without naming: the run says four definitions echoed, not which four, because the
  count is taken at the call and the gloss is not carried to it. Naming them is the obvious next
  improvement and was not made.

- **16 of 86 etymologies came back in English** on calls that succeeded, and the cause was this
  module, not the model: `etymology` was not in `SCHEMA["required"]`, so ollama's structured output
  let the model omit it, and `_etymology` turns an absent field into the text that was sent. The
  card then carried the English original with nothing in the run saying so. Requiring the field
  translates all eight failing etymologies, verified against the pages in the cache. What was ruled
  out on the way: length (the failures were *shorter*), citation density (44% against 41%), prompt
  wording, examples crowding the field out, and randomness — an identical call repeats itself 79
  times in 80.

- Removing the prompt's "if there is no etymology, answer with an empty one" was tried and is
  **worse**: it fixed one case on one model and broke three on the other. The line stays.

- `examples` is required for the same reason, and it measures larger: on ten cached glosses of four
  renderings each, requiring the field translated 36 of 36 where leaving it optional translated 11,
  refusing 25 — the model returned an array of the wrong length or none at all, and the whole set
  fell back untranslated. The measurement overstates the everyday case, though: those inputs put
  renderings from several senses behind one sense's definition, which decker never does, and the
  German run against the real pipeline refused none. Read it as insurance that measured well under
  stress, not as a bug the run was hitting.

- A run now says how much prose reached the cards untranslated, because until it did, this cost four
  probes to find. `Translator.kept` counts the two shapes that get there — a field answered empty,
  which the fallbacks replace with what was sent, and a field echoed back verbatim, which no schema
  can refuse — and `report()` prints one line before the card count:
  `[decker] 4 fields kept their English: 1 definition empty, 1 etymology echoed, 1 example echoed,
  1 examples refused`. Silence means every field came back in the mother language.

- Neither the schema nor the fallback can catch an *echo* — a model answering with the English it
  was given. `gemma3:4b` does this on three of the eight; it is a well-formed non-empty string and
  passes every check there is. A run cannot currently say how many fields failed to translate, and
  that is the gap that made this cost four probes to find.

- A few definitions came back untranslated too (`servilleta` as `Servilleta`), and one example kept
  English words inside German prose — `Ich bin kein sailor; ich bin ein captain`. Those are the
  model, and nothing here refuses a partly-translated answer.

## Known gaps

- Every card lands in one deck with no subdecks, tags beyond `recognition`/`production`, or
  scheduling presets. The design says to dump a deck, and the order is carried by `due`, so anything
  further is the learner's to set up in Anki.

- The examples on a recognition card are the ones Wiktionary happens to give the sense, which for
  many senses is none. Nothing generates them.

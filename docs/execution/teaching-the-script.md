# Teaching the script

Written by an AI agent, not by hand. It records the choices taken while implementing
`--teach-script`, which the design lists under *Future possibilities* as **closed-form writing
schemes** — "should identify whenever the target language's writing system differs from the original
(even if it's just pronounciation) and teach it" — and which Bru asked for on 2026-09-16 as "a
default-off flag to teach the script, meaning every displayed symbol in a card that's not in the
mother tongue must be taught". [The design](../instructions/design.md) remains the source of truth:
where this contradicts it, the design wins and the code is wrong.

## The rule, taken literally

The instruction is not about languages, it is about cards: *every displayed symbol in a card that's
not in the mother tongue must be taught*. So the stage does not ask "is Russian written in another
alphabet" once per run; it reads the text of every card decker is about to build and, for each
character on it the reader cannot yet read, puts a card teaching that character in front of it.

That reading is what makes the stage worth having. A Spanish deck for a reader of English is not "a
different writing system" by any language-level test, and it still shows `ñ`, `¡`, and a dozen IPA
symbols on nearly every card. The literal rule catches those; a language-level one would have said
Spanish and English share the Latin alphabet and stopped.

Everything below follows from taking it at its word.

## What counts as foreign: the repertoire, not the Unicode script

The obvious implementation compares Unicode scripts — Cyrillic against Latin — and it is wrong in
the case that matters most. `ʃ` is `LATIN SMALL LETTER ESH`. So are `ɾ`, `ʝ` and `ɲ`. Every IPA
reading decker puts on a card would have passed a script test untaught, and the readings are the
half of a card the design explicitly names ("even if it's just pronunciation").

So the test is a *repertoire*: the set of characters a reader of the mother tongue actually reads.
`decker/script.py` holds it, and it has three parts.

- **The shared characters**, which every writing system decker has been pointed at uses: the ASCII
  digits, the ASCII punctuation and space, the typographic spellings of the same marks (`–` `—` `‘`
  `’` `“` `”` `…`), the printer's marks any page carries (`•` `§` `©` `°` `±` `×` `÷` `′` `†`), and
  the digits again in superscript and subscript. Not "Unicode's Common script", which would swallow
  `¿`, `«` and `。` — punctuation that is exactly what an English reader has to be taught.

  The third group was added because a run produced it: Wiktionary's own bullet came off the
  definition of *мальчик* and a subscript two off the etymology of *на*, and `Symbol: • BULLET` is
  not a card anybody should be shown. Modifier letters stay out of it — `ʰ` and `ʲ` are how IPA
  writes aspiration and palatalization, and teaching those is the point of the stage.

- **The mother tongue's letters**, from `_ALPHABETS`, with upper case derived rather than written
  out. One entry, `en`, because v1 assumes English as the mother language and English is the only
  repertoire anything here has been run against.

- **Nothing else.** `familiar()` answers `None` for a language it has no entry for, and the stage
  then says so and stands down:

  ```
  [decker] --teach-script does not know which characters a reader of Portuguese already reads, so
  nothing is taught about the script (decker.script._ALPHABETS is where one goes)
  ```

  An invented alphabet is worse than no stage: it teaches a reader letters they have written all
  their life, or leaves out the ones they have not, and the cards look right either way. The bar for
  adding an entry is the bar `languages.py` sets for its tables — a run that was seen to need it.

Two smaller decisions inside the same test. **Case is not folded**: `Д` and `д` are two shapes and a
learner taught one has not been taught the other. **Invisible characters are dropped**: controls,
the bidi and zero-width marks, every kind of space — a card fronted by one would be unanswerable.
A **combining mark** is shown on U+25CC, the dotted circle typography already uses for it, so the
card teaching Hebrew's dagesh shows `◌ּ` and not an empty line.

## Where a symbol card's text comes from

Wiktionary first, as with everything else in the pipeline. A character is a page title, and the page
is read twice over:

1. **The target language's own section**, which is where a language writes about its own writing.
   `ж` gives *The eighth letter of the Russian alphabet, called жэ*, with `[ʐ]` and a recording;
   `ñ` gives *The fifteenth letter of the Spanish alphabet, called eñe*.
2. **`Translingual`**, where the IPA symbols, the punctuation and the Han characters live, for the
   characters no language claims.

Only the parts of speech that talk about the *shape* — `Letter`, `Punctuation mark`, `Han
character`, `Syllable`, `Diacritical mark`, `Number` — and, kept deliberately apart, `Symbol`, which
is how Wiktionary heads a piece of notation. The separation is not decoration; it is the difference
between a right card and a wrong one:

> **`¡`, met in a Spanish sentence.** Its Translingual section carries one entry: *Symbol — (extIPA)
> A sublaminal lower-alveolar percussive (tongue slap)*. That is a true statement about the glyph
> and a false card for a learner of Spanish, and the first version of this stage made it — and dragged
> `ǃ`, `ǂ`, `⟨` and `⟩` into the deck behind it, from the definition's own prose. The inverted
> exclamation mark is documented on the combined page `¿ ?`, which `¡` and `¿` redirect to, and
> decker does not follow redirects.

So a character met **in the text** is asked about as writing and may not be answered with a notation
entry, while a character met **in a reading** is asked about as notation first. `¡` then falls
through both to the last resort below, which says `INVERTED EXCLAMATION MARK` — thin, and true.
Which of the two a character is asked as is settled the first time it is met and then kept: a glyph
is one card in a deck, whichever half showed it first.

**The last resort is the Unicode character database.** `ú`, `ó` and `⟨` have no entry decker can
reach, and the name is what the card carries, with an attribution line saying so rather than the
Wiktionary credit every other card gets — the same admission a rule card makes about its model.

Symbol cards carry **the readings and the recording of the block they were read from** and **no
examples**. The readings are the point of the exercise; the examples on a letter's page are words
the learner has not met, and every one of them would pull more characters in.

## Ordering, dependencies and what is not made

- **A symbol card is a dependency of every card that displays its character**, and is appended to
  the gloss list immediately before the first of them, so its index is lower and the shuffle's
  topological sort keeps it ahead however the week is shuffled. This is the same mechanism concept
  cards use, and the script goes in front of the concepts: a card the reader cannot read is not
  improved by their knowing what *dative* means.

- **A letter's own card is read the same way**, which is where it gets interesting: `ж`'s definition
  is written in Cyrillic and its reading in IPA, so teaching one letter pulls in the letters and
  symbols its own card shows, and the alphabet arrives in dependency order. `pending` breaks the
  cycles this creates — `ж` reaches `э` reaches `ж` — by not depending on a card that does not exist
  yet. Both are taught; only the edge is dropped.

- **A character the text already teaches as a word is not taught twice.** The first gloss whose form
  *is* that character answers for it: the reader has met the shape, which is all the dependency
  asserts. This is what keeps a Chinese deck from carrying a `Symbol: 水` behind its `水`.

- **No production pair**, by the design's rule that only word definitions get one. "Given *voiceless
  palatoalveolar sibilant*, write the symbol" is a phonetics exercise, and the direction of a script
  that is worth drilling — writing it by hand — is not something a deck can mark.

- **The card is titled `Symbol: ж`**, prefixed like `Concept:` and `Rule:`, and for one reason
  beyond consistency: without the prefix a Chinese deck holds two cards fronted by `水`, the
  character and the word, with nothing on either to say which question is being asked. The prefix is
  English and, like the other two, is not translated — a gap this stage inherits rather than adds.

## What it costs

Measured on 1,400 characters of *Las medias de los flamencos* — 15 sentences, 212 terms — Spanish
read by a speaker of English, `--no-audio`, everything else default:

| | glosses | cards | words | concepts | rules | symbols |
|---|---|---|---|---|---|---|
| without `--teach-script` | 242 | 438 | 392 | 37 | 9 | — |
| with | 353 | 549 | 392 | 37 | 10 | 110 |

**+111 glosses, +110 cards, a quarter more deck, and not one word card changed.** The rule card that
appears in the second row is not the flag's doing: the first run wrote the twelve rules into
`~/.cache/decker/rules/es.json`, and the second run met one of them as an instance of a rule already
known rather than as the one that writes it. The symbol cards carry no production pair, so 110
glosses are 110 cards and not 220.

The shape of the cost is not the same in every language, and it follows from the rule rather than
from the implementation:

- **A Latin-script language** pays for its own extra letters, the punctuation English does not use,
  and the IPA inventory of the readings. The 110 above break down as 48 Latin letters (the IPA
  vowels and consonants, and the accented letters of Spanish and of every language its etymologies
  quote), 19 IPA modifiers and combining marks, 6 others (`¿ ¡ ⟨ ⟩ ⁽ ⁾`) — and **37 letters of
  other scripts entirely**, 16 Greek, 9 Devanagari, 8 Arabic and 4 Gothic, every one of them from an
  etymology rather than from the Spanish. The first three groups saturate: a language has one
  alphabet and decker has one transcription system. The fourth does not, and is the next paragraph's
  subject.
- **An alphabet in another script** pays for the alphabet, once — and pays for it immediately,
  because each letter's own card is written in the alphabet it belongs to. *Мальчик побежал на
  пляж*, four terms, gives 93 glosses of which 82 are symbols: 32 Cyrillic letters (28 lower case
  and the four upper-case ones that turn up in the prose), 27 Latin and IPA characters from the
  readings, and 23 others — the `⟨◌⟩` an IPA entry writes its examples in, Devanagari `झ` and
  Arabic `ژ` off the transliteration entry for `ž`, and `πλάγιος` off the etymology of *пляж*. One
  sentence has bought most of the script, and a later deck built with `--previous` leaves out every
  symbol card the first one already carries, the keys being gloss keys like any other.
- **Chinese pays per character displayed**, and there is no saturation to wait for. That is the
  honest consequence of the rule and the strongest argument for the flag being off by default.

The run cost is one page fetch per distinct character, cached like every other page, and no model
call at all: nothing here is a judgement, so nothing here asks a model.

**Most of these cards are thin, and it is worth knowing how thin.** 69 of the 110 carry nothing but
the Unicode name, because the English Wiktionary documents `ā`, `◌̞`, `ال`'s letters and the Gothic
alphabet under titles or sections this stage does not reach. The 41 that do find an entry are the
ones worth having — the alphabet's own letters, and the IPA symbols, which is where the readings
are. A deck built with the flag is a deck with a few dozen good script cards and a tail of
`LATIN SMALL LETTER O WITH MACRON`.

**The contract was checked by reading the deck back**, ad hoc from a scratchpad, the way v1 checks
everything: walk the cards in study order, collect every character each one displays, and report any
that no earlier card taught. On the one-sentence deck for *El niño corrió a la playa* it is **30
such characters over 18 cards without the flag and 0 over 35 with it** — the thirty being `ˈ ʝ ʃ ʒ ɾ
ɲ í ú á ü` and, off `el`'s etymology, the Arabic `ا` and `ل`. On the 1,400-character deck above it
is **1,303 over 438 cards without the flag and 1 over 549 with it**.

That one is the cycle guard, and it is the only shape of hole the stage leaves: `é`'s entry is
written *as opposed to è*, and `è`'s in terms of `é`. Whichever is reached first is still `pending`
when the second one is built, so the second takes no dependency on the first, and the shuffle is
free to put it earlier. Both are taught, a card or two apart. The alternative is a dependency edge
into a gloss that does not exist yet, which is a cycle the topological sort would have to break by
dropping something — a worse trade for a card the reader meets twice in the same minute.

## What it does not do

- **Redirects are not followed.** `¿` and `¡` redirect to `¿ ?` and so fall through to their Unicode
  names. Following them is a change to `pages.py` that would touch every word decker fetches, which
  is not something this stage should decide.
- **Etymologies are read like any other prose, and they quote every language there is.** `el`'s
  etymology — *False cognate of Arabic ال (al-)* — teaches `ا` and `ل` in a Spanish deck, and over
  1,400 characters of Quiroga that is **37 of the 110 symbol cards**: Greek, Devanagari, Arabic and
  Gothic letters, none of which the Spanish text ever shows. It is exactly what the instruction says
  — the card displays them — and it is the flag's main cost. Dropping the etymology from the scan is
  a one-line change in `_Builder.add`, and would leave at most 73 symbol cards of the 110, fewer
  once the accented letters that only an etymology quotes went with them. It has not been made: the
  rule as written is what was asked for, and a reader who cannot read a card's etymology is in the
  position the flag exists to fix.
- **Prose is only scanned while it is the prose the reader will see.** Cards are translated after
  the glosses are built, so with a mother tongue that is not the edition's, the English on its way
  through is not something anybody is shown and is not read for symbols. Today this is theory: the
  only repertoire decker knows is English's, and English is the edition.
- **It says nothing about handwriting, stroke order or letter names beyond what the entry says.**
  A `Symbol:` card teaches the shape, its sound and what Wiktionary calls it. That is recognition,
  which is the half a deck can ask for.

# Teaching the script

Written by an AI agent, not by hand. It records the choices taken while implementing
`--teach-script`, which the design lists under *Future possibilities* as **closed-form writing
schemes** — "should identify whenever the target language's writing system differs from the original
(even if it's just pronounciation) and teach it" — and which Bru asked for on 2026-09-16.
[The design](../instructions/design.md) remains the source of truth: where this contradicts it, the
design wins and the code is wrong.

## What it teaches, and what it deliberately does not

The first version read the instruction — *every displayed symbol in a card that's not in the mother
tongue must be taught* — as being about the whole card, and it was too much: it took in the
definition, the examples, the etymology and the readings, so a one-sentence Spanish deck came back
teaching the Arabic quoted in `el`'s etymology and the IPA of `playa`'s transcription. Bru narrowed
it the same day, and the narrowing is the design of the stage:

> I only want it to kick in for symbols in the very same term, not in the definitions, nor IPA, nor
> anything. And I want latin alphabet to act as one. I don't think it's worth it to teach /ç/. But
> if you're learning Japanese, I think learning the Hiragana (or the kanas) is gonna be part of it.

So the stage asks one question per gloss: **is this term written in characters the reader has?**
Every character of the term that belongs to a script the mother tongue does not use becomes a
`Symbol:` card, appended immediately before the gloss and made a dependency of it. Nothing else on
the card is read — not the definition, not the transcription, not the examples.

Two consequences worth stating plainly, because they are the point and not an omission:

- **A Spanish deck for a reader of English gains nothing**, and the run says so: `ñ`, `á` and `ü`
  are Latin letters with a mark on them, and `ç` is not worth a card.
- **A Japanese deck teaches the kana and the kanji its terms are made of**, one card each, before
  the word that uses them.

## Scripts, not alphabets

The test is Unicode's notion of a script, read off the character's own name — `CYRILLIC SMALL LETTER
ZHE`, `HIRAGANA LETTER A`, `CJK UNIFIED IDEOGRAPH-98DF`. `decker/script.py` keeps the list of script
names it knows and takes the first one a character's name mentions, hyphens split as spaces so that
`KATAKANA-HIRAGANA PROLONGED SOUND MARK` is katakana and `FULLWIDTH LATIN CAPITAL LETTER A` is
Latin. Unicode has already done the work; there is nothing here to keep current but a list of names.

- **A character whose name mentions no script has none**, and is never taught: the digits, the
  punctuation, `¿`, `%`, and the IPA modifiers. A writing system is what the flag is about.
- **A combining mark takes the script of the character before it.** `COMBINING ACUTE ACCENT` names
  no script, and the acute on a Latin `e` is part of a Latin word; the Hebrew points, which name
  Hebrew themselves, are taught along with the letters.
- **Case is not folded.** `Д` and `д` are two shapes, and a learner taught one has not been taught
  the other.
- **What the mother tongue reads is a table**, `_READS`, with one entry: `en` reads Latin. Under any
  other `--mother-lang` the stage says so and stands down:

  ```
  [decker] --teach-script does not know which scripts a reader of Portuguese already reads, so
  nothing is taught about the script (decker.script._READS is where one goes)
  ```

  Guessing is worse than not running: decker would be asserting which writing systems this reader
  already has, and both ways of being wrong — teaching them their own alphabet, leaving a script
  untaught — produce cards that look fine. The bar for an entry is `languages.py`'s bar for its
  tables: a run that was seen to need it.

## Where a symbol card's text comes from

Wiktionary first, as everywhere else in the pipeline. The character is a page title, and the page is
read twice over: **the target language's own section**, which is where a language writes about its
own writing, and **`Translingual`** for the characters no language claims. Only the parts of speech
that talk about the shape, `SHAPE_PARTS`, most telling first:

| the character | what its card says |
|---|---|
| `ж` (ru) | Russian *Letter* — the eighth letter of the Russian alphabet, called жэ — with `[ʐ]` |
| `あ` `ん` (ja) | Japanese *Syllable* — the hiragana syllable あ (a), and where it sits in the gojūon |
| `食` `子` (ja) | Japanese *Kanji* — to eat; child |
| `ー` (ja) | Japanese *Combining form* — the long-vowel mark |
| `ָ` (he) | Translingual *Letter* — the Hebrew vowel sign kamatz, with `/a/` |
| `的` (zh) | Chinese *Definitions* — bright; clear; distinct |
| `辺` (ja) | Japanese *Noun* — place, general area, vicinity |
| `한` (ko) | nothing; the card carries `HANGUL SYLLABLE HAN` |

Four of those rows were decisions a run forced:

- **Word parts of speech stay out.** Korean `한` heads a Numeral, a Determiner and four more, and
  *one (as a determiner numeral)* is a card about a word that happens to be one syllable long, not
  about the syllable. `Number` and `Numeral` were in the list until that run; they came out.
- **`Kanji` is asked before `Syllable`.** `子` heads the kanji for *child* and, further down the
  same section, an obsolete man'yōgana spelling of the katakana `ネ`. The first version taught the
  obsolete syllable.
- **A Han character may be answered by a word entry — and only a Han character.** `Definitions` is
  how the English Wiktionary heads a Chinese entry and the only place a Han character's meaning is
  written: `的` has no Translingual section at all. `辺` has neither, heading Nouns and Suffixes
  instead, so the section's own first sense answers. In a Han script the character *is* a morpheme;
  in an alphabet it is not, and the same rule would have taught Russian `я` as the pronoun.
- **The Translingual section may not answer with `Symbol`.** Its `¡` is an extIPA percussive, which
  would be a false card for a term that merely contains the glyph. A language's own section may,
  since a Symbol there is about that language.

**The last resort is the Unicode character database**: the name, with an attribution line saying so
instead of the Wiktionary credit every other card gets — the same admission a rule card makes about
its model. `한` is the case that turns up: the English Wiktionary writes Hangul one jamo at a time
(`ᄒ`, `ᅡ`, `ᆫ`), and decker does not decompose a syllable block into them.

Symbol cards carry **the readings and the recording of the block they were read from** and **no
examples**. The reading is what makes a kana card teach a sound rather than a shape; the examples on
a letter's page are words the learner has not met.

## Ordering, dependencies and what is not made

- **A symbol card is a dependency of every term that contains its character**, and is appended
  immediately before the first such gloss, so its index is lower and the shuffle's topological sort
  keeps it ahead however the week is shuffled. The characters go in front of the concepts: a card
  the reader cannot read is not improved by their knowing what *dative* means.
- **A character the text teaches as a word is not taught twice.** The first gloss whose form *is*
  that character answers for it: the reader has met the shape, which is all the dependency asserts.
  It is what keeps a Chinese deck from carrying a `Symbol: 水` behind its `水`.
- **Symbol cards have no dependencies of their own.** They did in the first version, which read each
  letter's own definition and reading and so pulled a whole alphabet in behind one word, cycles
  included — `ж` is defined in terms of `э`, and `э` in terms of `ж`. Reading only the term removes
  the cascade and the cycle together.
- **No production pair**, by the design's rule that only word definitions get one. The direction
  worth drilling the other way — writing あ when asked for the syllable *a* — is handwriting, which
  a deck cannot mark.
- **The card is titled `Symbol: あ`**, prefixed like `Concept:` and `Rule:`, and for a reason beyond
  consistency: without the prefix a Chinese deck holds two cards fronted by `水`, the character and
  the word, with nothing on either to say which question is being asked. The prefix is English and,
  like the other two, is not translated — a gap this stage inherits rather than adds.

## What it costs

Measured with `--no-audio --no-rules`, read by a speaker of English:

| source | terms | glosses without | glosses with | symbols |
|---|---|---|---|---|
| *El niño corrió a la playa* | 6 | 11 | 11 | 0 |
| *Мальчик побежал на пляж* | 4 | 11 | 26 | 15 |
| 男の子は浜辺へ走った | 6 | 6 | 16 | 10 |

- **A Latin-script language costs nothing at all**, and the run says so rather than leaving it to be
  inferred: `every term is written in the mother tongue's own script; --teach-script added nothing`.
- **An alphabet costs the alphabet, and costs it in the first few sentences**: four Russian words
  have fifteen distinct letters between them, and the whole language has sixty-six counting both
  cases. A later deck built with `--previous` leaves out every symbol card the first one already
  carries, symbol glosses having gloss keys like any other.
- **A character-based script costs per character the text shows**, and there is no saturation to
  wait for — six Japanese terms cost ten symbol cards, and the kanji among them will keep coming.
  That is the honest consequence of the rule, and the reason the flag is off by default.

The run cost is one page fetch per distinct character, cached like every other page, and no model
call at all: nothing here is a judgement, so nothing here asks a model.

## What it does not do

- **It does not teach the transcription.** A card still shows `[ˈmalʲt͡ɕɪk]` to a reader who has
  never seen `t͡ɕ`. That is Bru's call — "not the definitions, nor IPA, nor anything" — and the
  version that did teach it cost 110 symbol cards on 1,400 characters of Spanish where this one
  costs none, most of them Greek, Devanagari and Arabic letters quoted inside etymologies.
- **It does not decompose.** A Hangul syllable block is one character to Unicode and one card to
  decker, and it falls back to the Unicode name because Wiktionary documents the jamo instead.
- **It does not know handwriting or stroke order**, and says nothing a Wiktionary entry does not.
  A `Symbol:` card teaches the shape, its sound and what the entry calls it — recognition, which is
  the half a deck can ask for.
- **It follows no redirects**, so a character documented under a combined title (`¿` under `¿ ?`)
  would fall back to its Unicode name. With punctuation out of scope this no longer bites, and
  following redirects is a change to `pages.py` that would touch every word decker fetches.

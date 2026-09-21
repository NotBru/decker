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
read section by section until one of them says something: **the target language's own**, which is
where a language writes about its own writing, then **`Translingual`** for the characters no
language claims, then — for a Han character only — the words the target language writes with it, and
last the other languages that took the character. Only the parts of speech that talk about the
shape, `SHAPE_PARTS`, most telling first:

| the character | what its card says |
|---|---|
| `ж` (ru) | Russian *Letter* — the eighth letter of the Russian alphabet, called жэ — with `[ʐ]` |
| `あ` `ん` (ja) | Japanese *Syllable* — the hiragana syllable あ (a), and where it sits in the gojūon |
| `食` `子` (ja) | Japanese *Kanji* — to eat; child |
| `ー` (ja) | Japanese *Combining form* — the long-vowel mark |
| `ָ` (he) | Translingual *Letter* — the Hebrew vowel sign kamatz, with `/a/` |
| `的` (zh) | Chinese *Definitions* — bright; clear; distinct |
| `辺` (ja) | Japanese *Noun* — place, general area, vicinity |
| `下` (ja) | Japanese *Noun* or *Affix* — whichever of its five etymologies the term is read with |
| `娘` (ja) | Japanese *Noun* — daughter, and not Chinese's *mother* |
| `한` (ko) | nothing; the card carries `HANGUL SYLLABLE HAN` |

Several of those rows were decisions a run forced:

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
- **Which of a kanji's etymologies answers is the text's to decide, not the page's.** 下 heads a
  Japanese `Kanji` block that is readings and no gloss, and its Translingual section is stroke
  counts, so the answer comes from the words written with the character — of which there are five,
  した, しも, もと, げ and か, unrelated words under five numbered etymologies. Taking the first was
  taking the top of the page. The term that asked for the card picks instead: 靴下 is read
  *kutsushita*, so した answers and the card says *the underneath*; 地下 is *chika*, so か answers and
  it says *down; below; beneath*. The test is whether a block's own reading is inside the term's
  (`_as_read`), which rendaku and the sound changes of compounding will defeat — 今日 is read
  *kyō* and no character in it is read at all — and when it fails the first block stands, which is
  what there was before. It costs nothing to be wrong and is right whenever it fires.
- **Another language's section is the last thing asked, not the first.** The first version of this
  read a Han character's meaning from Chinese, on the theory that the meaning belongs to the script;
  the run that followed within the hour said otherwise. 靴 is a *boot* in Chinese and a shoe in
  Japanese, and 娘 is *mother* in Chinese and *daughter* in Japanese. A borrowed character carries a
  borrowed meaning and the meaning drifts, so the target language answers about its own writing
  wherever it says anything at all — about the character, and failing that about the words written
  with it — and `HAN_SOURCES` (zh, ko, vi) is for the character its section does not mention.

**The last resort is the Unicode character database**: the name, with an attribution line saying so
instead of the Wiktionary credit every other card gets — the same admission a rule card makes about
its model. `한` is the case that turns up: the English Wiktionary writes Hangul one jamo at a time
(`ᄒ`, `ᅡ`, `ᆫ`), and decker does not decompose a syllable block into them.

Symbol cards carry **no examples** — the examples on a letter's page are words the learner has not
met — and **a reading only where the block that answered is the character's own**.

Wiktionary draws most of that line by itself, a pronunciation sitting under the block it belongs to:
`あ` heads a Syllable with `[a̠]`, `ん` takes its `[ɴ]` from the section above the etymologies, `ж`
has `[ʐ]`, `ا` has `/ʔa.lif/` and `/ʔ/` — the name and the value — and Chinese 友 has `/joʊ̯²¹⁴/`,
a hanzi being one syllable. `食` has none, and is right to: its readings are on the five words below
it. So the reading is the answering block's own, and none where the block answering is a word's or
another language's — a Mandarin reading is no more a fact about a kanji than a Japanese word's is.

**But a kanji has no pronunciation at all, and the structure does not quite say so.** 下 was
carrying `[ɕi̥ta̠]` — one of *shita*, *shimo*, *moto*, *ge*, *ka*, picked by page order and printed
as though the character were read that way. Five more survived the block rule: 務's section numbers
one etymology, so its `Kanji` block inherits the reading of the one word つとむ written with it and
looks for all the world like the character's own. It is not. `script.speaks` is the rule that says
so and `_MANY_READINGS` is its whole content — **`ja`**, one entry, because Japanese is the one
living language that reads a character several ways: it took the characters from Chinese twice, as
go-on and kan-on, and wrote its own words with them besides. A hanzi is one syllable of Mandarin and
a hanja one of Korean; only a kanji is a relation rather than a value, and the honest card is the
silent one.

The reading is then met where it is true — on 靴下's card, which has carried it all along — and the
silence is the convention rather than a gap in it: *Remembering the Kanji*, the kanji deck a learner
would otherwise be using, gives a character one English keyword and defers every reading on purpose.

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
- **A production pair, since 2026-09-18**, at Bru's instruction. The card had none until then, by
  the rule that only word definitions get one; the argument against it was that writing あ when
  asked for the syllable *a* is handwriting and a deck cannot mark it. That argument holds for no
  production card — a deck cannot mark a typed answer either, the learner does — and it is the
  direction a reader of a new script is weakest in. It is what separates a symbol from the other two
  glosses decker titles itself: the answer to `Concept: dative case` is a name decker wrote, and the
  answer to a symbol's is a character.
- **The question is masked where it spells the answer out.** A character's definition is written
  around the character — *The hiragana syllable る (ru). Its equivalent in katakana is ル (ru)* —
  and that sentence is the whole of the production card's question, so 102 of the Gokurakugai
  deck's 487 symbols were being asked for in front of the answer. Every piece of the answer becomes
  `■` (U+25A0 BLACK SQUARE): `Symbol: The hiragana syllable ■ (ru). Its equivalent in katakana is
  ル (ru).` Bru's call, 2026-09-18, and the square is his word for it — it reads as *a character
  goes here* in every script, is in no alphabet decker teaches, and cannot be mistaken for the
  answer the way `_` or `?` could in a deck that also teaches punctuation.

  **Only the answer's own code points, and every one of them.** The mask is literal: ル is left
  standing in る's question, because it is a different shape with a card of its own, and `д` is
  left standing in `Д`'s *called дэ*, because case is not folded here either and `д` is a card the
  reader has already met. Masking what merely resembles the answer would blank the deck's other
  cards out of the prose that explains them. Going the other way, every instance goes, not the
  first: た's position line is `■行あ段`, since た行 shows the shape as plainly as the headword
  does. A combining mark is masked with its carrier and on its own, the whole form first, so `◌ָ`
  is one square rather than two.

  A word card's question is masked too, by the same square and a different rule — the whole term,
  never its letters one by one; wherever it stands where `script.foreign` says the reader could not
  have read it anyway, which is this stage's own test doing a second job, and where they could,
  only where Wiktionary's self-link markup says the definition is quoting its own word.
  `deck-building.md` has it.

  It is presentation on one side of one card. The gloss keeps Wiktionary's prose, so the
  recognition card, `gloss_key`, `--previous` and the timeline see what they saw before; what
  changes is the guid of the symbol production notes, identity being the front and the definition
  together, so a collection already holding them re-introduces those cards rather than rescheduling
  them.

- **The `Symbol: ` prefix moves to the question on that card.** The production challenge is the
  definition, and a bare *drink* in a Japanese deck could be asking for 飲 or for 飲む, which are two
  cards in it; `Symbol: drink` says which. It is the narrowing `_fronted` does on a marked sense, and
  by the same rule — it says which answer is wanted, not what it is. The answer side drops the
  prefix: what the learner writes is 飲. A longer gloss reads as a label on a sentence — `Symbol: The
  hiragana syllable み (mi)…` — which is the price of the marker riding inside the definition field;
  a field of its own would change the note type of every deck already built.
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
  wait for — six Japanese terms cost ten symbol glosses, and the kanji among them will keep coming.
  That is the honest consequence of the rule, and the reason the flag is off by default.
- **Every count in the table above is glosses, and a symbol gloss is now two cards**, as a word's
  is: the 487 symbols of the Gokurakugai deck cost 974 cards where they cost 487 before.

The run cost is one page fetch per distinct character, cached like every other page however many of
its sections are read, and no model call at all: nothing here is a judgement, so nothing here asks a
model.

## What the Gokurakugai deck says about all this

The 2026-09-19 rules were checked by rebuilding the manga deck — 443 sentences, 2,284 terms, 483
symbol cards, 370 of them kanji — and reading the `.apkg` back:

| | before | after |
|---|---|---|
| kanji symbol cards carrying a reading | 95 | **0** |
| kanji symbol cards playing a recording | 6 | **0** |
| kana symbol cards carrying a reading | 99 | 99 |
| symbol definitions that changed | — | 6 |

The recordings are the sharpest of it: `Symbol: 娘` played *musume*, `Symbol: 誰` played *dare*,
`Symbol: 春` played *haru* — a word's voice on a character's card, and there is no other reading a
learner could have taken it for. All six are gone, and every kana recording stayed.

Six definitions changed, and each is the term that asked for the card choosing its own block:

| character | was | is | the term that asked |
|---|---|---|---|
| 初 | the first…, initial… (*hatsu*) | beginning, start (*sho*) | 最初 *saisho* |
| 分 | minutes (duration) (*fun*) | a part, a share, a portion (*bun*) | 自分 *jibun* |
| 我 | first person singular pronoun: I, me (*ware*) | the ego, self (*ga*) | 怪我 *kega* |
| 野 | an area, field (*no*) | field, plain (*ya*) | 野郎 *yarō* |
| 者 | person (*mono*) | someone of that type (*sha*) | 者 |
| 次 | next, secondary (*shi*) | next, order, sequence, below (*ji*) | 次 |

Each asking term is the first the deck meets that character in, and the four compounds read it the
new way outright: 最初 is *saisho* and not *hatsu*, 怪我 is *kega* and not *ware*. 者 and 次 are the
character standing alone, where the term's reading is the reading of the sense the deck teaches
first, and the block follows it. 477 of the 483 were already on the block the page put first; the
rule moves the ones it was built for and leaves the rest alone.

**One thing the inspection turned up that is not this change's doing.** 179 of the 483 characters
also have a word card of their own in the same deck, and in 83 of those the two cards say the same
sentence — `Symbol: 者` and `者`, identical but for the prefix. The "a character the text teaches as
a word is not taught twice" rule below only fires when the word came first: `symbols_in` runs while
the word's own gloss is still being built, so a character whose first appearance *is* the standalone
word gets both cards. It is a gap in that rule, older than these two, and it is not fixed here.

## What it does not do

- **It does not teach the transcription.** A card still shows `[ˈmalʲt͡ɕɪk]` to a reader who has
  never seen `t͡ɕ`. That is Bru's call — "not the definitions, nor IPA, nor anything" — and the
  version that did teach it cost 110 symbol cards on 1,400 characters of Spanish where this one
  costs none, most of them Greek, Devanagari and Arabic letters quoted inside etymologies.
- **It does not decompose.** A Hangul syllable block is one character to Unicode and one card to
  decker, and it falls back to the Unicode name because Wiktionary documents the jamo instead.
- **It does not know handwriting or stroke order**, and says nothing a Wiktionary entry does not.
  A `Symbol:` card teaches the shape, its sound and what the entry calls it. Its production card
  asks for the character and takes the learner's word for what they wrote, which is what every
  production card does; what it cannot do is say the strokes went in the wrong order.
- **It follows no redirects**, so a character documented under a combined title (`¿` under `¿ ?`)
  would fall back to its Unicode name. With punctuation out of scope this no longer bites, and
  following redirects is a change to `pages.py` that would touch every word decker fetches.

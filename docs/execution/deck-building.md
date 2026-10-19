# Deck building: implementation choices

Written by an AI agent, not by hand. It records the choices taken while implementing the last three
stages of v1 — deck construction, shuffling and Anki output — which refine [the v1
design](../instructions/v1/design.md) without changing its shape. The design documents remain the
source of truth: where one of these contradicts them, the design wins and the code is wrong.

## Cards

- The two faces are dataclasses of their own (`Side`), carrying only the pieces the design puts on
  that face, so a card is the design's two bullet lists rather than a bag of fields a renderer picks
  from. The Anki templates then only have to lay out what is there.

- The production card depends on its recognition card and on nothing else. Whatever the gloss
  depends on is already behind that recognition card, and the ordering the design asks for is
  transitive, so naming the rest again would only be a second way to say the same thing.

- **Which glosses get the pair.** Word definitions, and — since 2026-09-18, at Bru's instruction —
  symbol cards, whose answer is a character the reader has to be able to write. Concepts and
  morphological rules still get the recognition card alone: their title is decker's own prose, so
  producing it from its explanation is a question about decker's naming. A symbol's production card
  carries its `Symbol: ` prefix on the *question* — `Symbol: drink` asks for 飲, where a bare *drink*
  could be asking for 飲む — and drops it from the answer; the marker rides inside the `Definition`
  field rather than in one of its own, a new field changing the note type of every deck already
  built. `Gloss.title_prefix` is what the card builder takes off and puts on, so nothing here knows
  what a symbol is.

- **A production question is masked where it spells its own answer out.** A definition often
  quotes the term it defines — *the hiragana syllable る (ru)*, *分かる, 解る: to be understandable*,
  *short for 金玉 (kintama): testicles* — and that definition is the whole of the production card's
  question, so printed as it stands the card answers itself. In the Gokurakugai deck it did so 177
  times: 102 of its 487 symbols and 75 of its word cards. The answer is replaced by `■` (U+25A0),
  the shape a font shows when it has nothing to show. Bru's call, 2026-09-18, symbols first and
  words the same day.

  **A symbol is masked piece by piece**, `Symbol: The hiragana syllable ■ (ru)…`. *Piece*, because
  the answer can be more than one code point — a combining mark is shown on its carrier, `◌ָ` — and
  the definition may quote either the pair or the mark alone; the whole form is replaced first so
  the pair becomes one square and not two.

  **A word is masked whole, never letter by letter**: one square for the term however long it is,
  `■, 解る: to be understandable`, `short for 金■ (kintama)`. Blanking the letters of `casa` out of
  *house* would take the house with it, so it is the term or nothing. *Where* it is masked is two
  rules, one per script:

  **A term the reader could not have read is masked wherever it stands.** The test is
  `script.foreign(term, reads)` against `script.scripts_of(--mother-lang)` — the same test and the
  same one-line table `--teach-script` runs on. One character of another script is enough, since
  the match then carries that character and cannot land inside the mother tongue's own prose, which
  is why this half may replace blindly, 玉 inside 金玉 included.

  **The same-script case was tried by guesswork first and cost too much.** Masking a Latin term
  inside English prose wherever it stood alone as a word — `\w` on neither side — left the
  Gokurakugai deck with five cards the mask had taken apart: `The hiragana syllable あ (■)` for the
  romaji card `a`, the same for `no` and `do`, and `(` defined `Used in ■ )`. Standing alone as a
  word is no protection when the term *is* an English word, and German `in`, defined *in, into*, is
  `■, into` however the boundary is drawn. Bru's call, 2026-09-18: apply it only where the scripts
  differ.

  **So it is now asked rather than guessed, and the wiki answers exactly.** Bru's call,
  2026-09-20, on the card that started it: German `müssen` is defined *(auxiliary, with an
  infinitive → “müssen” replaces the past participle) to have to…*, and that production card
  printed its own answer under the 2026-09-18 rule, German and English sharing an alphabet.
  MediaWiki renders a link to the page one is already on as a **self-link**, and on a Wiktionary
  page a self-link carries the language section it points into:

  | in the German entry of… | the markup | what it is |
  |---|---|---|
  | `müssen`, *“müssen” replaces…* | `<a class="mw-selflink selflink">` | the German word — **mask** |
  | `der`, *inflection of der* | `<strong class="selflink">` | the German word — **mask** |
  | `nice`, *good, nice* | `<a class="mw-selflink-fragment" href="#English">` | the **English** word — leave |
  | `in`, *in, into* | no markup at all: prose | English — leave |

  `pages._quoted_in` reads it into `Sense.quoted`, the gloss carries it, and `_unspelled` masks a
  same-script term only where the definition quotes it *in the language being taught*. So German
  `in` keeps *in, into* on three senses and is masked on the fourth, *(dated) contraction of ■ +‎
  den*, where the wiki says the `in` is the German one. Only where the term stands as a word of its
  own, for this half — the answer is spelled in the reader's own alphabet here, and a blind
  replacement turns `e`'s definition, *The name of the Latin script letter E/e*, into
  `Th■ nam■ of th■ Latin script l■tt■r E/■`.

  A quotation is compared after composing and dropping what will not compose, so Russian `ру́сский`
  is recognised as `русский` — a mention carries the stress the entry is not titled with. Stripped
  on the quotation's side only, so Spanish `papá` is not masked by a definition that quotes `papa`.

  Measured over the warm page cache, per sense, for a reader of English:

  | | senses | definition says its own term | **newly masked** | left alone |
  |---|---|---|---|---|
  | German | 585 | 44 | **13** | 31 |
  | Spanish | 2,952 | 86 | **6** | 80 |
  | Russian | 15,855 | 95 | **5** | 1 |
  | French | 377 | 55 | 0 | 55 |
  | Japanese | 5,368 | 170 | 0 | 25 |
  | Chinese | 4,549 | 29 | 0 | 14 |

  Japanese and Chinese gain nothing because the script rule already had them; Russian's five are
  the stress-marked quotations the blind replacement missed. **And what is left alone is the point
  of the whole exercise**: all 31 German and all 80 Spanish are the mother tongue's own word
  standing in the definition of a word spelled like it — `(colloquial) good, nice`, `wild (of
  animals, etc.)`, `Seine (a river in France)`, `(zoology) coral`, `medio, half-real (a former
  coin)`. Every one of them would have been blanked by a substring rule, and none of them is the
  leak.

  **A term quoted inside a longer term is measured and left.** `ellipsis of golpe de estado`,
  `only used in acerca de` — the answer stands there as a word, but the wiki links the *phrase*,
  not the term, so it is not a self-link. Masking inside any `lang`-marked mention would reach
  them: 6 Spanish senses and 4 German. Four of the ten are wrong — `abbreviation of ■-Dur` for
  `A`, `Separated form of ■-` for `nach`, `alternative form of ■.` for `Mi` — because a term that
  is the *beginning* of the term the definition names is not the answer leaking, it is the
  question. Four genuine cards are not worth four damaged ones, and this is the note that says so.

  Presentation only, on that one side — the gloss, its key, `--previous`, the timeline and the
  recognition card all keep the prose Wiktionary wrote. A note's identity is its front and its
  definition together, though, so a production note that gains a square gains a guid: a collection
  already holding those cards re-introduces them rather than rescheduling them. Nineteen word
  cards over the whole warm cache, which is the size of the thing being traded for a card that
  stops printing its answer.

- A gloss's dependency becomes the *recognition* card of the gloss it depends on, not its production
  card. What `patita` needs from `pata` is that the reader have met the word; being able to produce
  `pata` from its meaning is a further skill, and waiting for it would hold `patita` back for no
  reason the definition gives.

- **A figure of a word is fronted with its label.** Since a sense marked `(poetic)`,
  `(figuratively)`, `(colloquial)` and so on now drags its plain sense into the deck with it (see
  `definition-fetching.md`), a learner meets the same front twice — `мрак` for *shadow, darkness*
  and `мрак` for *(poetic) despair* — with nothing to say which answer is wanted. So the recognition
  card of a marked sense is fronted `мрак (poetic)`, `уйти (figuratively, poetic)`, `дни
  (figuratively)`. Bru's call, 2026-09-17.

  The label narrows the question rather than leaking the answer: it says which register is being
  asked for, not what the word means there. The production card needs nothing — its front *is* the
  definition, label included — and its answer stays the bare word, because the label is not part of
  the spelling.

  It is read off the translated definition, so a deck in another mother tongue shows the label its
  own back shows, and off Wiktionary's where the translation dropped the parenthesis. Presentation
  only: `gloss_key`, the rules stage and `--previous` all see the spelling they saw before. The
  Anki note's guid does change for these cards, since identity is the front and the definition
  together — a handful of cards per deck, re-introduced rather than rescheduled.

- The sound file rides on the answer of *both* cards, next to the IPA. This is a small widening
  of the design, whose answer list names etymology, IPA and definition: the reading and the
  recording answer the same question, and v1 downloads the file already, so leaving it out of the
  deck would mean fetching audio the learner never hears. If the design meant the list to be
  exhaustive, this is the line to cut.

  The production card had the reading and not the recording until 2026-09-18, when Bru asked for
  it there too: the answer to a production card *is* the word, and how the word sounds is part of
  producing it. It costs nothing to carry — the file is downloaded for the recognition card
  anyway, and both cards name it by the same bare filename, so the package holds one copy. The
  `Audio` field is appended to the production note type rather than inserted next to `IPA`, so a
  collection that already holds decker's production notes gains a column instead of having its
  existing fields renumbered under the notes in it; the templates lay it out where it belongs
  regardless. Media files are collected into a dict for that reason too — genanki writes one file
  per entry it is handed, so the list the two cards would have produced would pack every recording
  twice.

- **A character's readings ride there too, beside the IPA and under the same rule.** A kanji has no
  pronunciation of its own, so its card carries the `Readings` list Wiktionary gives it instead —
  `Kan-on: けつ (ketsu, Jōyō)` — on the answers of both cards and never on a front: it says how the
  term is read, and a production card whose question showed it would be reading out half its own
  answer. Only a gloss whose term is one character has one, so nothing appears on a Spanish or
  Russian deck at all. The field is appended to both note types, for the reason `Audio` and
  `Renderings` were. Where it comes from is
  [Definition fetching](definition-fetching.md); what it is for is
  [Teaching the script](teaching-the-script.md).

### What a card carries of the source text: the word, and nothing else

Worth stating outright, because it is load-bearing and because nothing enforces it. A `Gloss` holds
the inflected form, the entry it was read from, Wiktionary's definition, examples, etymology and
IPA, the audio paths, and — for a rule card — prose a model wrote. **No sentence of the source text
is anywhere on a card.** The text is read to decide *which* words to teach and in what order, and a
sentence of it goes into the disambiguation prompt to settle a sense; neither survives into a
gloss, so neither reaches the deck.

What that buys, in order of how much it matters:

- **A deck is distributable in a way the source text is not.** A `.apkg` built from a copyrighted
  work — a subtitle track, a novel — contains Wiktionary's CC BY-SA text, a model's prose, and a
  list of which words the work uses in the order a learner should meet them. It does not reproduce
  the work. That is a much weaker thing for a rights holder to object to than a deck of its
  sentences would be, and it is the reason the licensing section can talk only about Wiktionary.
- **The example sentences on a card are Wiktionary's**, which is also why they are attributed to it
  and why the translator is allowed to touch the rendering half and not the sentence half.
- **It is not an accident and it is not defended.** Adding the source sentence to the recognition
  card is an obvious feature request — it is the sentence the learner actually met — and it would be
  a real improvement to the deck. It would also change what a deck *is*, from a word list into a
  quotation of the work, and every sentence above stops being true. If that is ever built, the
  licensing section needs rewriting in the same commit.

The prompts are the other half of this: a hosted model backend sends those sentences verbatim to a
third party. `model-backends.md` records that as privacy exposure; for a text that is not the
user's own it is a copyright question too, and the ollama default is what keeps both answers simple.

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
  prose and is the only half a model may touch. The rendering is what is sent, so no answer can
  rewrite a sentence — and where there is no rendering to send (below, *Examples the edition leaves
  bare*) what comes back is still only ever used as one. Joining them first and splitting on the em dash looked equivalent and was not: the
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

- Failure is the same degraded run disambiguation has: warn once, keep what Wiktionary wrote. A
  host that was named and has stopped answering is not a failure but an outage, and is waited for
  ([When a remote stops answering](connectivity.md)). A deck
  in the wrong language is worth more than no deck.

### The titles decker writes itself

- A card titled `Concept: ditransitive verb` over a Spanish description was asking a Spanish speaker
  to know English in order to study English. The titles decker writes — a concept's, read out of
  `Appendix:Glossary`, and a rule's, written from an inflection line — are English because the
  edition is, and they are not words of the language being taught, so they go through the
  translator like any other prose: `Concepto: verbo ditransitivo`, `Regla: forma comparativa
  (older)`. Bru asked for it on 2026-09-19, having found it in an English deck built for Spanish.

- Half a title, not the whole of it. `Gloss.title_prose` is the part that is decker's prose and
  `title_prefix` the pile it names; the rest of `surface` is the language and stays in it — the
  `(older)` a rule is named after is the word being taught, and a translated representative would
  teach the wrong one. The pile's word is one call for the whole run, however many concepts a text
  needs.

- The gloss itself is never touched. `gloss_key`, `--previous` and the rule book under
  `~/.cache/decker/rules/` are all written against `surface`, so the translation happens on its way
  onto the card and nowhere else. A deck that renamed its own cards per mother tongue would stop
  recognising the decks built before it.

- **The schema's field name is an instruction.** Asked for `{"name": …}` — which is what the field
  holds — gemma3:4b and gemma4 both answered `present tense` to `present tense`: 33 of gemma4's 47
  answers came back untouched, several with the prompt's own conditions appended
  (`transitive verb (noun phrase, no article, no explanation…)`). A key naming the input asks for
  the input. Renaming it to `translated` and changing nothing else translated all 47. It is worth
  knowing generally: the keys of a structured answer are read as part of the prompt.

- The card's own description is **not** offered as context, which is the opposite of what it looked
  like it should be. Measured twice over the 47 glossary names a nine-episode English deck pulled
  in: with the description beside it the model stopped naming the term and started translating the
  description — `present tense` and `past tense` both came back `tiempo verbal`, one title over two
  different cards, and after the field rename whole sentences came back as titles. Without it, 43 of
  47 are the name a Spanish grammar would use. The ambiguous one-word names the context was meant to
  rescue — `focus`, `literal` — turned out to have been the field name's doing.

- A title that ends up standing for two cards is refused and both go back to English
  (`cards._unclashed`). It happened in each of the two sweeps — `archaic` and `obsolete` both became
  `arcaico` — and two cards with one front and two backs is the single thing the titling exists to
  prevent. Both of them, not the second: one card reading `Concepto: arcaico` and another
  `Concept: obsolete` would read as unrelated rather than as the pair they are. The run says how
  often it caught one.

### What the deck has to ask for when the edition is the language being taught

- Every other deck gets the mother tongue's word for free. `todavía`'s entry in the English
  Wiktionary *is* `still`, because the edition is written in the direction the learner needs. Turn
  the pair around — English taught to a Spanish speaker — and the entry for `still` describes the
  word instead, *up to a given time, as in the preceding time*, and translating that description
  yields a Spanish paraphrase of an English idea and never the word `todavía`. So it is asked for
  directly, once per sense, and put **above** the description rather than in place of it: the
  description is what tells this sense of `still` from the other nine, and the word is what the
  sense is worth knowing for. Bru's call, 2026-09-19.

- Only where the target language is the edition's own, and only for the glosses that teach a word.
  A concept and a rule are cards about grammar with no word to be the equivalent of, and a symbol is
  a character rather than a word; all three are the glosses decker titles itself, which is what
  `title_prefix` marks.

- It rides on the production card's question as well, above the description there too. That card
  asks for the word given the meaning, and `todavía` is the meaning said in one word. The one shape
  that could leak the answer — the model handing `still` back for `still` — is refused where it is
  asked for, and counted.

- It costs one call per gloss, on top of the one that translates it, and only in this one pairing of
  languages.

### Examples the edition leaves bare

- Wiktionary renders an example when the example is not in the edition's language. A Spanish
  sentence under a Spanish entry comes with its English beside it, and that rendering is what the
  translation stage puts into the mother tongue. An English sentence under an English entry comes
  alone — correctly, for a reader of English — so an English deck for a Spanish speaker showed
  `Is it still raining?` with nothing under it at all. Those sentences now get a rendering written
  for them, in one call per gloss.

- The rule that the sentence is never sent survives it. What comes back is used as the rendering and
  never as the sentence: the model writes the half it is allowed to write, and the half the card
  teaches is the one that arrived. An answer that does not line up one for one is refused whole, the
  way a translated rendering is, and a sentence handed back as its own rendering is dropped rather
  than printed twice.

## The shared ollama session

- Both stages that ask a model anything now go through `decker/ollama.py`: the host and its default,
  the prompt-under-a-schema call, reasoning turned off, and one warning per run naming which stage
  lost its model and what happened instead. Disambiguation moved onto it unchanged, which is what
  made translation a couple of dozen lines rather than a second copy of all of that.

## Shuffling

- The sort keys of a window are that window's own positions, permuted. Sorting by them can therefore
  move a card around inside its week and nowhere else, which is the design's window without any
  arithmetic about where a card is allowed to land.

- **Each window is shuffled and then put in dependency order by swaps** (since 2026-10-19). The
  sort sees one window's list and nothing else. It reads the list front to back; a card one of whose
  dependencies is still ahead of it swaps with a card drawn at random from that dependency's place to
  the end of the list, and the card that comes back is read next. A card that has to wait therefore
  lands uniformly somewhere after what it waits for, and one card moves for it, not everything in
  between. Swaps only send a card forward and past its dependency, so with no cycle it ends; a
  cycle, which cannot be built, stops it after a bounded number of swaps rather than hanging the run.
  A card whose dependency the source put in a *later* window is carried into the next window before
  that one is shuffled. One run's glosses never make such an edge (none in Gokurakugai 0001), but the
  backwards edge `glosses._after` draws could.

- **What it replaced, and why.** Until then the order was a stable topological sort, Kahn's
  algorithm taking the ready card with the smallest shuffled key: a card waited exactly as long as
  its dependencies made it wait and not one place longer. That last property was the fault. A
  production card whose key fell before its recognition card's — a coin flip — became ready with its
  turn already past, was the smallest key ready, and went out next: **half of all production cards
  sat directly behind their recognition card** (755 of 1,524 in `decks/japanese.apkg`), and a word
  directly behind its last symbol the same way. Bru's algorithm, with the swap his: shuffle without
  regard to order, walk the list, and send a card that is too early to a random place forwards.

  Over Gokurakugai 0001's own graph (3,108 cards, 4,239 edges, 1,524 recognition–production pairs),
  200 seeds each, window 140:

  | | toposort | swap sort |
  |---|---|---|
  | dependency violations | 0 | 0 |
  | production directly after recognition | 48.9% | 3.5% |
  | any dependent directly after its dependency | 22.3% | 1.7% |
  | median recognition → production gap | 1.8 | 22.6 |
  | mean distance a card moves from the source's place | 45.7 | 45.4 |
  | cards outside their source window | 0 | 0 |
  | time per deck | 3.6 ms | 4.0 ms |

  An ordered pair dropped at random into a 140-card window is adjacent 1.4% of the time; the swap
  sort's 3.5% is above that because a recognition card late in its week leaves its production card
  few places to land. The cost is a lean: dependents sit later in their week and free cards earlier
  — production cards at a mean place of 84 of 140 against 79 under the toposort, cards with no
  dependency at 40 against 49 — which is what "after what it waits for" means once it is not "right
  after".

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

- The three calls added on 2026-09-19 — the titles, the equivalent, the renderings for bare examples
  — were run against `gemma3:4b`, in the container and on the CPU, with the tunnel to the GPU box
  down. `Rule: comparative form` came back `Regla: forma comparativa`, with `(older)` where it was.
  `still` was asked for twice, once per sense, and answered `hasta ese momento` for *up to a given
  time* and `tranquilo` for *not moving; calm* — the sense reaches the model, which is the whole
  point of asking per gloss and not per word. `Is it still raining?` came back `¿Sigue lloviendo?`,
  and an example that already had a rendering was not sent at all. Two things the same run got
  wrong, both the model and neither the wiring: `ditransitive verb` became `verbo transitivo de
  segunda intención` where the GPU box's copy of the same model had said `verbo ditransitivo`, and
  the second of two sentences sent together came back carrying the first one's question mark.

- End to end, on `Is it still raining?` alone: 14 glosses, 20 cards, a package read back out of its
  own SQLite. Eight concept cards came out titled in Spanish — `Concepto: modo indicativo`,
  `Concepto: tiempo presente`, `Concepto: pronombre personal átono` — with one name echoed and the
  run saying so (`3 fields kept their English: 2 etymology empty, 1 title echoed`). Every example
  reached the back rendered: `Is it still raining? It was still raining five minutes ago.` under
  `¿Sigue lloviendo? Llovía hace cinco minutos.` And every word card carried its equivalent above
  the description — `still` → *hasta ese momento*, `is` → *es*, `it` → *se*, and `be` in its
  weather sense → *hacer*, which is the word a Spanish speaker actually says for `it is hot`. The
  model was `qwen3.5:4b` on the container's CPU, and it got one wrong: `raining` → *lluvioso*, an
  adjective where the form is *lloviendo*.

- The wiring the three calls hang off was checked separately from the model, by answering them from
  a table instead: five glosses — a word with two unrendered examples, a concept, a rule, and two
  concepts whose names were deliberately answered with the same Spanish word — through deck
  construction and into a package read back out of its own SQLite. `Concepto: tiempo pasado` and
  `Regla: forma comparativa (older)` came out titled, with `(older)` where it was written;
  `todavía` sat on the recognition card's back and on the production card's question and on neither
  of the concept cards; the two bare examples reached the back rendered and the front unrendered;
  and the pair that collided went back to `Concept: archaic` and `Concept: obsolete` with the run
  saying so. Ten fields on the recognition note and eight on the production one, `Equivalent` last
  on both, which is what keeps an existing collection's note type from being renumbered.

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

- `--description` sets what a deck says it was built from. The default is the input file's name,
  which is fine when the file is named for its source and wrong when it is not: a scratch file
  called `dw.txt` put `Built by decker from dw.` into a deck's permanent metadata. Wiktionary's
  attribution is appended whatever the flag says, since that is the licence's requirement and not
  a decoration — the flag replaces the provenance sentence, never the credit.

- A deck records what it teaches, so it can be handed back as `--previous`. Each note carries its
  gloss's key as the tag `decker::gloss::<hash>`, and `anki.taught` reads them out of the package.
  A tag rather than a field: a new field changes the note type of every deck already built, while a
  tag is something Anki carries, exports and imports without being told — so a deck the user has
  studied, edited and re-exported still answers the question. The deck is the record for the same
  reason: it is what the user has, what they move between machines, and what survives deleting
  everything else. Decks built before this carry no keys, and `--previous` on one says so rather
  than silently deciding nothing is new.

- **An incremental deck is numbered after the deck it is added to.** `--previous` says this build
  is an addition — its cards are the ones that deck does not teach — so `anki.last_position` reads
  the highest position among that package's *unstudied* cards and every card here starts above it.
  A studied card carries a due date rather than a position, on a scale that has nothing to do with
  this one, so those are not read; a deck studied to the end answers 0, which is right, there being
  nothing left for a new card to queue behind. Without `--previous` a deck is numbered from 1, as
  it always was: a rebuild is not an addition, and its own order is the order the whole deck wants.

  The offset is applied to the shuffled list, not inside the shuffle, so `--window` still means
  what it meant — cards move up to a week's worth of places from where the *source* put them, and
  the join between two builds is not a place anything shuffles across. An addition cannot reorder
  the deck it is added to, which is the property that makes this safe rather than the property
  that makes it ideal: a new card that ought to come before something already queued still comes
  after it. The design's ordering guarantee is about a deck, and two builds are two decks.

- **`--update DECK.apkg` carries the identities of a deck already in Anki.** A note's id is the
  card's kind, its entry and its prose (see above), so a card decker has since learned to write
  *differently* — the masking of 2026-09-20 is the case that raised this — is a new note under that
  rule, and importing it puts the corrected card in the collection **beside** the wrong one rather
  than over it. `--update` is the user naming the deck they already study: `anki.identities` reads
  each note's id and the gloss key it carries as a tag, and a card whose gloss that deck already
  teaches is written under the id it has there. Anki then updates the note it holds — fields
  corrected, scheduling untouched — and the cards that are genuinely new arrive as new notes.

  Keyed on the gloss and the side, never on the words, which is the whole point: the words are
  what changed. A note with no gloss key — a deck built before decker recorded them, a note the
  user wrote into the same deck themselves — matches nothing and is therefore left alone, and the
  run says how many notes it matched so a mismatched file is visible rather than silent.

  **The default identity stays the prose.** Making it the gloss key outright would be the cleaner
  scheme, and it would have made this flag unnecessary — but every note of every deck already
  built would change its id at once, so the next import would double a collection instead of
  correcting it. A flag costs a user who wants continuity one argument; a scheme change costs
  everyone who has studied anything. Bru's ask, 2026-09-20, was for the cards already in Anki to be
  corrected, and this is the way that does not break them to do it.

- **A deck exported by Anki 2.1.50 or later cannot be read.** That Anki writes
  `collection.anki21b` — the same SQLite database, zstd-compressed — and there is no zstd in this
  Python (3.14 is the first with one) or among decker's dependencies. Both flags that read a deck
  say so by name and stop before the run costs anything, naming the export dialog's *Support older
  Anki versions* checkbox, which writes the old format. Adding `zstandard` would remove the
  checkbox from the workflow and is a `pyproject.toml` change, so it is Bru's to make.

## Known gaps

- **An update cannot renumber the cards Anki already has.** Importing corrects the notes and adds
  the new ones, and leaves the scheduling of what is there — which is the point — but it means a
  card that ought to come *before* one already queued arrives after it instead: the old card keeps
  its old position and the new one is numbered on the rebuild's scale. So a component card added
  to a deck already being studied can turn up behind the word it explains. Anki's own *Reposition*
  is the tool for that, on the cards the import added; decker cannot do it from a package.

- Every card lands in one deck with no subdecks, tags beyond `recognition`/`production`, or
  scheduling presets. The design says to dump a deck, and the order is carried by `due`, so anything
  further is the learner's to set up in Anki.

- The examples on a recognition card are the ones Wiktionary happens to give the sense, which for
  many senses is none. Nothing generates them.

- **The example's rendering is on the back, and only the sentence is on the front.** An example is a
  pair — the sentence in the language being taught, and the edition's rendering of it — and showing
  the pair on the front of a recognition card answers the card: `Он в теа́тре — He's at the theater`
  under the word `в` hands the learner the meaning they were being asked for. The front shows the
  sentences alone; the renderings ride on the answer side, in the same order, as their own field.
  Their own field rather than a second copy of the examples, because the back already opens with
  `{{FrontSide}}`, and the sentences are right above where the renderings land.

  `Renderings` is appended to the recognition note type rather than inserted, like `Headword` before
  it: the model ids are stable, so a collection that already holds decker notes gains a column
  instead of having its existing ones renumbered underneath them. A production card has no examples
  and gains nothing.

- **The headword line is still the edition's English**, on every card that has one:
  `(not comparable)` under `still`, `(comparative greener, superlative greenest)` under `green`.
  It is the one piece of prose on a card that the mother tongue never reaches. It is also not one
  piece: `greener` and `greenest` are forms of the word being taught and have to survive untouched,
  while `comparative` and `superlative` are the same grammatical vocabulary the concept cards now
  translate, so it wants the treatment a rule's title gets — the frame translated, the quoted forms
  left alone — and not a call that hands the whole line to a model. Raised on 2026-09-19 and left,
  the same day's work going to the three things Bru asked for instead.

# Definition fetching: implementation choices

Written by an AI agent, not by hand. It records the choices taken while implementing v1's
definition fetching, which refine [the v1 design](../instructions/v1/design.md) without changing its
shape. The design documents remain the source of truth: where one of these contradicts them, the
design wins and the code is wrong.

## Where the data comes from

- One endpoint is read per title: the rendered page, `action=parse`. Everything a gloss is made of
  is in that HTML — the senses under each part-of-speech heading, their examples, the first
  paragraph under an Etymology heading, `<span class="IPA ...">` readings, and
  `upload.wikimedia.org` audio URLs. The raw wikitext would have been the obvious source and is not
  usable: Spanish pronunciation sections carry `{{es-pr|...}}`, and the IPA only exists once that
  template has run.

  It was two for most of v1. The REST definition endpoint (`/api/rest_v1/page/definition/<title>`)
  keyed its entries by language code, which is the cut the pipeline needs — the title dump has no
  language dimension at all — and rendered form-of definitions in full. Reading senses from the
  HTML instead made it redundant, and it is no longer asked for: "Senses are read from the rendered
  page" below has what that was worth, and why a mirror cannot serve it.

- The language *name* needed to find the section in the HTML (`Spanish`) comes from a code-to-name
  table, `languages.name_of`. REST used to name the language in its own payload, which is why no
  table was kept; the HTML offers no such handle, only the heading. The heading the entries were
  actually read under then replaces it, so a page that spells the name differently still decides
  what the gloss says.

- The payload is cached verbatim, one gzipped JSON per title under `pages-<edition>/`, so a page is
  fetched once however many terms land on it. The origin that rendered it is written into the same
  file — see "The page cache is keyed by title and edition" below — because a page from a mirror
  and a page from Wikimedia differ in exactly one way, and it is not the definitions. Audio stays
  out of that file, as the design asks: the page keeps the URL and the sound file is written under
  `audio/` only when it is wanted.

- Wikimedia answered a burst of back-to-back requests with HTTP 429. Requests are now spaced half a
  second apart and a 429 or 503 is waited out, honouring `Retry-After` when the server sends one.

- A page whose definitions come back as Wiktionary's own failure text — a Lua timeout, rendered into
  the page under a normal 200 — is used for the run but never written to the cache. Cached, such a
  page is permanent: `de` and `o` had sat there long enough that every run asked the model to choose
  between fifteen copies of `The time allocated for running Lua modules has expired`. Not writing it
  costs one degraded run and lets the next one get the real page.

- A title too large for one page keeps its language sections on `<title>/languages A to L` and
  `<title>/languages M to Z`, and shows a footer of links in their place. `a` is the one such title
  the Barbapedro text reaches: the definition API returned English alone, and so does the raw
  wikitext, so this is a split to follow rather than truncation to work around — parsing the HTML
  instead would have missed it just the same. When a page has that footer and no section for the
  language, both subpages are tried and the payloads of whichever answers are used whole, so the
  reading and the etymology come from the same place as the definitions. The gloss keeps the
  original title, since `a` is the word and the subpage is only where Wiktionary filed it.

## Glosses

- A term is glossed from the first of its entries that actually has a section in the target
  language. `El` matched both the `El` page (a Semitic deity, no Spanish section) and `el`; the
  first is skipped and the article is what gets glossed.

- Dependencies come from the definition, not from the parse. A sense that describes its word in
  terms of another names that word in its own text — `diminutive of pata`, `apocopic form of mío`,
  `first/third-person singular imperfect indicative of ser` — and that word is glossed and depended
  upon. Keying off Stanza's lemma instead had missed the whole class where the two disagree:
  `patita`, `mi` and `larguísimo` all lemmatize to themselves, so they carried no dependency while
  their definitions pointed at `pata`, `mío` and `largo`, none of which were glossed at all.

  Only the pointing sense gets the edge, which is why `era` the noun ("threshing floor") no longer
  claims to be a form of `ser` while `era` the verb still does, and why the interjection senses of
  `vaya` stand alone while its imperative sense depends on `ir`.

  Wiktionary names the referenced word in the sense that *opens* a part-of-speech block and lets the
  lines beneath it continue bare, so a bare line inherits the block's word — but only a block whose
  first sense names one, and only for lines that are themselves grammatical description. Keying off
  any sense in the block let `ir`, whose tenth definition mentions the past participle of reflexive
  verbs, hand `reflexive` to its neighbours.

  A referenced word is glossed at one sense, asked for on its own prompt: `patita` depends on
  `pata` as "paw, foot, leg", not on all eight of its senses, since each kept sense is a card pair
  the dependent card waits behind. Resolution recurses, and the chain of titles being resolved is
  carried down so a pair defined in terms of each other cannot loop.

  **Which sense is a question about the occurrence, not about the pointer.** It was asked as "the
  ONE sense that the description relies on", and an inflection's pointer relies on no sense at
  all: `stem form of 出る` says nothing about which 出る. On the first page of Gokurakugai,
  `出てください` is a telephone being asked to be answered, Wiktionary's fifth sense of 出る, and
  the deck taught the first, *to leave a place*. So the prompt now carries the passage with the
  occurrence marked, says how the word asked about relates to it — the definition that points at
  it, the sum an etymology names it in, or the figurative sense a plain one is wanted under — and
  asks which sense of it the marked occurrence carries there. One prompt for all three kinds, with
  one sentence of relation each (`disambiguation.RELATIONS`).

  **The answer can only be one number.** These questions were decoded under the same schema as
  the occurrence's own, a list, and "exactly one" in the prompt did not hold a 4B to it: over the
  volume, 276 of 804 came back with every sense listed, and `keep` took the first in page order for
  each without saying so. That is how `下さる` became *to give* and `出る` *to leave*. The schema
  for them is now `{"sense": integer}` (`SCHEMA_ONE`), which the output is decoded under rather than
  asked for. The first sense still stands where there is no answer — no model reachable, or a number
  not on the list — which is what a run without a model has always taught.

  Neither change makes a small model read a telephone call out of `もータオさんいんなら出てくださ
  いよお`; the phone is in the picture, and in `あい、…事務所っす`, the way the office answers. Asked
  the new prompt, `qwen3.5:latest` chose *to answer*; `qwen3.5:4b`, `gemma4:latest` and `qwen3:14b`
  chose *to leave*, and `gpt-oss:20b` with thinking off said nothing. The prompt now puts the right
  sense in front of the model with what it needs to choose it; the rest is the model.

- The other half of a dependency comes from the etymology, not the definition: where an etymology
  states a sum of terms **in the language being taught** — `descargar` is `des- +‎ cargar`,
  `venenoso` is `veneno +‎ -oso` by surface analysis — those terms are glossed and depended upon by
  the same machinery, one sense each, recursively, chain-guarded. Only a sum, so a doublet, a cognate
  and a `Compare` list name nothing; only that language, so the Latin an etymology walks back through
  stays prose on the card. `--no-components` turns it off, and
  [The terms a word is made of](etymological-components.md) has the detection, the precision and the
  cost.

- A gloss carries one sense, not a page's worth: every sense that survives disambiguation becomes a
  gloss of its own. Identity is then the pair the design names — the inflected form plus that one
  sense — so a sense met twice collapses even when the two occurrences kept different sets around it.
  Bundling every surviving sense into one gloss had made two whole bundles distinct whenever they
  differed by a single sense, which is how `ir` came to be glossed twice from one sentence.

- Because each kept sense is now a card pair rather than another line on one card, over-keeping costs
  real cards, and the prompt asks for as few senses as truly apply — usually exactly one — instead of
  every sense that plausibly fits. The same shift makes a disambiguation outage far more visible:
  keeping every sense used to yield one fat gloss and now yields dozens, so a degraded run is hard to
  mistake for a good one.

- Glosses are appended in the order their terms occur, and a lemma's gloss is appended just before
  the inflected gloss that needs it, so the index increases with occurrence and a dependency always
  precedes what depends on it.

- Where a term has more than one spelling, every entry they reach is fetched and their senses are
  numbered as one list for disambiguation, so the model chooses a meaning instead of the pipeline
  choosing a spelling. `Bueno` reaches a surname and `bueno` an adjective; pooled, the sentence
  decides. The page most of the surviving senses came from is the one the gloss is built from, since
  a gloss carries one entry, one etymology and one reading; senses kept from another page are dropped
  with a warning.

- A gloss is then spelled the way that page spells it, so `Cuando` glossed from `cuando` is one gloss
  rather than two identical ones, while `España` keeps its capital. **Always that page's spelling**,
  including where the entry is a different word: a form Wiktionary has no page for is glossed from
  its lemma's, and that card is the lemma's card. It used to keep the text's form on the front, and
  Bru found what that produces in a deck he was studying (2026-09-16): a card fronted `Упавшего` —
  sentence-initial capital included — whose back was `упасть`'s definition *to fall, to drop*,
  `упасть`'s reading `[ʊˈpasʲtʲ]` and `упасть`'s example sentence. A card that asks for a participle
  and answers with an infinitive is wrong in the direction that matters, and nothing on the back of
  it admitted the swap. Where the form does have a page — `упавший` does, *past active perfective
  participle of упасть* — nothing changes: it is glossed from its own entry and depends on the
  lemma's, as before.

- The Markdown renderer gives `depends_on` a line of its own — **Depends on** [0. ser](#0-ser) —
  rather than a bare index trailing the fact line, where it was unreadable and unnavigable. The link
  targets the dependency's own heading, which the design's ordering guarantee already puts above.

- A gloss carries the sound file's URL as well as its cached path. The path is only set when the run
  downloaded audio; the URL is kept either way, so `--no-audio` still yields a document that links to
  the pronunciation. The Markdown renderer prints the URL and never the cache path, which would mean
  nothing to a reader.

## Sense disambiguation

- **A prompt gets a passage, not a sentence, when the sentence is too short to say anything.** The
  design's unit is the sentence and it is the right one for prose. Dialogue is where it runs out:
  Bru's Russian series folds into 6,158 sentences with a **median of six tokens**, and six tokens do
  not distinguish one sense of a word from another. So below a floor the neighbouring sentences are
  added, alternately behind and ahead — behind first, since in dialogue a line answers what was just
  said — until the floor is reached or the text runs out. The occurrence is still bracketed inside
  its own sentence, so the passage has exactly one mark in it however long it is.

  Two numbers, both measured on `gemma4:latest`, and the second is the one worth reading:

  | | nine checks | glosses | Hebrew glosses | Hebrew: cards from the prefix entries |
  |---|---|---|---|---|
  | sentence only | 7/9 | 38 | 259 | **8** |
  | 12-word floor | 7/9 | 40 | 259 | **8** |
  | 20-word floor | **8/9** | 41 | 279 | 27 |
  | 40-word floor | **8/9** | 41 | 282 | 28 |
  | 80-word floor | **8/9** | 41 | — | — |
  | **20 words, open class only** | **8/9** | 41 | **258** | **8** |

  Twenty words is the least that recovers the check a five-word sentence loses — `—Vaya, vaya a
  dormir.` needs its neighbour to be read as the subjunctive of `ir` — and more than twenty buys
  nothing. But the same context that saves `vaya` inflates Hebrew: its clitic prefixes carry
  twenty-three senses apiece, and with neighbours the model stops choosing and starts hedging, 8
  cards becoming 27 for the same seven words.

  The two cases differ in kind, and `CONTEXT_FOR` is the difference: **context is given to a word
  that has a meaning to choose, and withheld from one that has a page of fine distinctions instead**
  — UD's open classes plus `INTJ`, which is where `vaya` lives when it is not a verb. Every Hebrew
  prefix is `ADP`, `DET`, `CCONJ` or `SCONJ`, so none of them is given any, and the last row is what
  ships: the benchmark's gain and none of Hebrew's cost. Spanish prose does not notice either way —
  276 glosses with the window and 276 without — because its sentences are already past the floor.

  **Asked of every model, the rule turns out to be one model's guard.** Hebrew, cards built from the
  prefix entries, with the rule and without:

  | model | rule on | rule off |
  |---|---|---|
  | `gemma4:latest` | **8** | **27** |
  | `qwen3.5:4b` (the default) | 12 | 15 |
  | `gemma3:4b` | 19 | 19 |
  | `qwen3:14b` | 9 | 8 |

  On the 24-check benchmark it changes nothing for any of them — 22, 21, 16 and 23 of 24 either way,
  gloss counts within two. `gemma3:4b` does not move because it keeps everything regardless, and
  `qwen3:14b` is one card *better* without it. So the rule is kept as insurance for a model that is
  one `--model` flag away rather than because the default needs it, and this paragraph is what says
  what dropping it would cost: three cards in Hebrew, and nothing anywhere else that was measured.

- **The parse's part of speech is in the prompt, as a hint.** The survey's Hebrew run taught five of
  the commonest words in the language as names of letters: Stanza splits the clitic prefixes off, as
  it should, and a one-letter token's page offers the letter of the alphabet beside everything else,
  with a sentence-context prompt giving a small model nothing to choose between them with. The parse
  knew all along — the token is an adposition — and nothing downstream was being told. `keep()` now
  takes the term's UD tag and `reading_of` turns it into a sentence: *the parse reads the marked
  occurrence as an adposition (a preposition or a postposition); prefer a sense listed under that
  part of speech*. A hint and not an instruction, because a parse is wrong sometimes and
  Wiktionary's part of speech is not always UD's. Tags that say only what a thing is not — `X`,
  `SYM`, `PUNCT` — produce no line, since a hint the model cannot act on is prompt spent for nothing.

- **…except where the capital is what made the tag.** `PROPN` on a word whose capital belongs to its
  position is the one tag the hint fabricates. Stanza reads `Надежда казалась мне солью` as a proper
  noun and `надежда казалась мне солью` as a noun — one letter, and the lemma with it — and the
  prompt then told the model to prefer the sense listed under that part of speech, which is *a
  female given name, Nadezhda*. Term extraction had already ruled the capital suspect by offering
  the lower-case spelling, and `надежда`, *hope*, was sense 2 in the same listing. Bru found the card
  in the Stigmata deck, 2026-09-16; 39 terms in a 6,165-sentence subtitle run hit the same rule.

  So where the term is `positional_capital`, the tag is `PROPN`, and some candidate page is
  lower-case, the hint is replaced by what decker actually knows: *the marked occurrence begins its
  line or its sentence, and a word in that position takes a capital whatever it is … judge it as
  though it were written in lower case*.

  **Withholding the tag was not enough, and the wording is held together loosely.** With the hint
  simply gone, `qwen3.5:4b` still answered the given name. It is the last clause that turns the
  answer over: the same claim without *judge it as though it were written in lower case* loses it
  again, and so does the same sentence rearranged around an em-dash. `gemma4:latest` and
  `gpt-oss:20b` answer *hope* under every wording tried, the broken `PROPN` hint included. Read that
  as a 4B at its ceiling rather than a prompt with a hole in it.

- **A sense labelled as a figure is taught on top of a plain one, not instead of it.** `мрак` in a
  Stigmata lyric came back `(poetic) despair`, which is defensible in the line — «Потерянный мрак,
  которым ты жила» — and was the whole of what the deck taught about the word: a metaphor with
  nothing under it. `уйти`, reached through `ушла`, came back `(figuratively, poetic) to die` where
  the line says *left*. Bru's call, 2026-09-17: when a chosen sense carries one of these labels —
  poetic, figurative, colloquial, archaic, dated, obsolete, slang, literary, humorous, ironic,
  euphemistic — the page is asked again with the labelled senses removed, and the plain sense that
  comes back is glossed *first*, with the marked card depending on it the way a form-of card depends
  on its base word.

  Not every parenthetical: `(anatomy)`, `(with dative)`, `(impersonal)` say which use of the word
  this is and depend on nothing. These are the ones that say the sense is a figure, a register or an
  age — a reading a learner cannot arrive at from the word alone. A page whose every sense is
  labelled gets nothing, there being no plain reading to teach. One extra model call per marked
  sense chosen; six fired over the 41 lines of `stigmata.txt` (`мрак`, `уйти`, `умереть`, `дни`,
  `так`, and one repeat), so the stage costs about what it teaches.

  It interacts with the benchmark, and the benchmark had to be told: a check that says the senses
  kept for a surface *must not* say X will now see the plain sense as well as the figure. `beber` in
  `bebe de la tradición` is the check written for that case — it asks only that *draw from* is
  there, and lets *to drink* stand beside it.

- **A clitic is looked up under the title Wiktionary gives a bound morpheme.** The hint above was
  not enough, and the measurement said why: the preposition is not on the page at all. `ל` is a page *about the letter* — Lamed, the twelfth letter, and two noun senses — and the
  preposition is at `ל־`, with a maqaf. The model was choosing correctly among what it was shown.
  What the parser calls a clitic is what the tokenizer split *off* — a word of a multiword token that
  is not its last — and for a language in `languages._JOINERS` that form is also looked up with the
  joiner attached; the title has to exist for it to be offered. Both spellings then go into
  `Term.spellings`, so their senses are *pooled* the way `Bueno` and `bueno` are, rather than one
  ranked behind the other: which of them the term is depends on the sense, which is the model's
  question and not the pipeline's. The table holds one language, because one has been measured — a
  hyphen is the Latin-script spelling of the same idea and would be wrong for it, since Spanish `del`
  splits into two *free* words and pooling the prefix `de-` into the preposition `de` would offer a
  morpheme the sentence never used. Seven prefixes, 62 of the Hebrew sample's 333 term occurrences,
  reach their real entries this way: ל ב ה ו ש מ כ.

  Measured on the survey's Hebrew sample, one arm per fix, `gemma4:latest` over the tunnel:

  | | cards for the seven prefixes | from the prefix's own entry | a letter of the alphabet | glosses |
  |---|---|---|---|---|
  | neither fix (the survey's run) | 9 | **0** | 7 | 264 |
  | the part-of-speech hint alone | 12 | **0** | 6 | 270 |
  | the bound title alone | 12 | **9** | 3 | 262 |
  | both, which is what ships | 11 | **8** | 3 | 265 |

  The second row is the finding worth keeping: told to prefer an adposition among senses none of
  which is one, the model hedged and kept *more* wrong cards — the numeral 2, a lexicographic
  initialism — rather than fewer. A prompt cannot choose a sense that is not in front of it, and
  that is what "try the part-of-speech hint" was worth on its own. With the title, ל teaches *to*,
  ב *in*, ה the definite article, ו *and*, ש *introduces a subordinate clause*, מ *from* and כ
  *like, as*; three of them keep the letter's card alongside, which is a sense the page really has.

  The third row is why the hint stays anyway. It does nothing for `gemma4:latest`, which is
  discriminating enough without it — but `qwen3.5:4b`, the default, answers the title alone with 39
  cards for those seven words and 302 glosses, and with the hint as well with 19 and 271. A page
  with 23 senses is exactly where a model needs telling which part of speech it is looking for. On
  the nine-check Spanish benchmark the hint takes `gemma4:latest` from 7/9 to 8/9 — it recovers
  `vaya` as the subjunctive of `ir` — and leaves `qwen3.5:4b` at 8/9 with five glosses fewer.
  Spanish and German decks are otherwise unchanged by it: 277 glosses against 276, and 286 against
  289, with a dozen substitutions either way.

- One ollama call per glossed occurrence, carrying the sentence with the occurrence bracketed, the
  form as it appears, and every sense of the page numbered and labelled with its part of speech; the
  model answers with the numbers it keeps, under a JSON schema. On `El perro corrió hacia la
  puerta` this cut `la` from eleven senses to the article alone and `correr` from thirteen to
  three.

- The default model is `gemma4:latest` since 2026-10-11 (`qwen3.5:4b` before it), on the criterion in `model-backends.md`: inside a
  ten-second-a-card ceiling the scarce resource is the learner, not the clock, so the default is the
  model that answers the most questions right for the fewest cards. Measured cold on the
  four-language benchmark, it passes 22 of 24 checks in 288 s where `gemma4:latest` passes 21 in
  373 s and `gemma3:4b` passes 16 while producing a hundred more glosses; `qwen3:14b` passes 23 and
  takes four times as long, which is what `--model` is for. It also fits the laptop at 3.3 GB. A
  model can be named once for a whole shell as `$DECKER_MODEL`, the way the host is named by
  `$OLLAMA_HOST`, because those two are exactly the pair that has to agree: a tunnelled GPU box and a
  laptop's own ollama hold different tags, so a host set in the environment and a model left to its
  default is the ordinary way a run asks for something that is not there. When it does, the warning
  names the tags the host *does* hold. The host defaults to `$OLLAMA_HOST`, falling back to
  `http://localhost:11434`, ollama's own default; ollama has no authentication, so it is never bound
  anywhere but a loopback or a tunnel.

- **A character's block is not one of the word's senses.** Bru found the card on 2026-09-22, in the
  Gokurakugai deck: `街 — main street or boulevard`, with four kanji readings under it and no
  pronunciation. That is not a sense of the word 街 at all. A Japanese page heads a `Kanji` block
  above its etymologies and what that block glosses is *the shape*; the word the text used is two
  blocks below it — the suffix `-gai`, *town, district, area*, `[ɡa̠i]`. Pooled into one numbered
  listing the character's gloss is simply candidate number one, and either the model picks it or,
  with no ollama to ask, the first sense stands and it is picked by default.

  `Page.word_senses` is the listing a word is now chosen from: every sense whose block is not one of
  `_CHARACTER_PARTS` — kanji, hanzi, hanja, han character, character, letter, syllable — which is
  the same set that decides where a `Readings` list may hang. The shape's gloss has a card of its
  own already, the `Symbol:` card, and it is read out of these very blocks. A page whose *only*
  blocks are character blocks keeps them: a kanji the language writes no word with alone still has
  to gloss as something, and what the page says about the shape beats no card at all.

  Measured over the 10,903 pages this machine had cached, per language section:

  | language | pages with a section | with a character block | and it was candidate one |
  |---|---|---|---|
  | Japanese | 1,254 | 268 | **268** |
  | Russian | 8,222 | 30 | 30 |
  | German | 178 | 17 | 17 |
  | Spanish | 860 | 13 | 13 |
  | Chinese | 631 | 2 | 0 |

  Japanese is where it bites — a fifth of its pages, and the block is *always* on top, because
  Wiktionary writes the character before the etymologies that use it. Elsewhere it is the single
  letters (`т`, `ß`, `e`), where the word cards were competing with *the twentieth letter of the
  Russian alphabet*. Chinese is untouched by design: `Definitions` is how the English Wiktionary
  heads a Han character's meaning and the only place it is written, so it is not in the set and 的
  still glosses.


## Fetching, and the page it reads

- **The section heading is named by a table of decker's own, not by Stanza's.** A gloss is read from
  the language's `<h2>`, and the name that finds it came from Stanza's four hundred codes, which
  agree with Wiktionary's headings nearly everywhere — and not for Chinese: Stanza calls `zh-hans`
  *Simplified Chinese* and the page 狗 heads its section `Chinese`. Unpatched, every Chinese lookup
  returned nothing and the deck was empty. `languages.section_of` is that table, and it is five
  entries long: the three Chinese codes, and `nb`/`no`, where Stanza says *Norwegian* and `hund` and
  `bok` both head `Norwegian Bokmål`. An entry goes in when a run has been seen to find nothing
  because of it, never on suspicion. What a *prompt* calls the language is left alone — a text in
  `zh-hans` really is in Simplified Chinese, and `name_of` still says so.

- **A page that points somewhere else is read where it points.** The English Wiktionary writes a
  simplified Chinese spelling as a box that points at the traditional one — 人类's whole Chinese
  section is "For pronunciation and definitions of 人类 – see 人類" — and the sense reader, looking
  for a numbered list, found a page with nothing on it. `_points_at` reads the box (a table whose
  class names the language's own see-template, `zh-see`) and `_from_pointer` re-reads the section at
  the title after the word "see": one hop, inside the language section only, and the title stays the
  one the text used, because 人类 is the spelling the reader met and 人類 is only where the
  dictionary keeps the definitions. On the survey's Chinese sample this took coverage from **82 % to
  99 %** — 240 glosses to 302 — and the four occurrences still without an entry are *Canis lupus*,
  *Cendrillon* and *Cenerentola*, which are not Chinese.

  **Japanese words the same way, from 2026-09-18.** A manga deck reported 116 terms with no Japanese
  section and **89 of them had one** — 飲む, 分かる, 出来る, ください, 無い, 取る, ダメ, バカ — every
  one a spelling the dictionary files under another. `ja-see` is the same template family and
  `_points_at` already matched the box; two things stopped it reading the target:

  - **The two editions word the sentence differently.** Chinese names the spelling in it (*see
    人類*), so the target is the first link after the word. Japanese does not (*see the following
    entry*) and sets the target below, in a 【 】 block beside the definitions. `_SEE_ENTRY` is that
    block's link, and it is tried when the sentence named nothing.
  - **The box has a table inside it.** The entries pointed at are laid out in one, so the old
    non-greedy `(.*?)</table>` ended at the *inner* table's close — after the first entry and before
    every other. `_see_box` counts table depth instead. Reading a box for a single target the old way
    answers `みる` with `ミル` and looks entirely right doing it.

  **One target is followed and several are not**, which is Bru's call of the same day. 68 of the 89
  name one spelling; the other 20 are kana strings pointing at a pile of homophones — いん at
  nineteen kanji words, みる at both ミル and 見る. Those are not spellings of one word, they are a
  list of the words that sound alike, and mostly reached from a fragment Stanza cut rather than from
  a word the text used. Taking the first of them is the answer decker refuses to give anywhere else
  (see [term extraction](term-extraction.md) on entries, and the audio rule in this document), and
  pooling nineteen entries into a disambiguation prompt is a cost with nothing behind it. So a box
  naming several targets is left where it was: no section, and `--unknowns` answers for it.

- **A redirect is followed, and takes the title with it.** A hard redirect renders as the redirect
  notice and nothing else — no language section, no senses — so the word reached the definer with
  nothing. `грез` in a Russian text lemmatises to `греза`, which the English Wiktionary keeps as a
  redirect to `грёза`, and the word was dropped; with the unknown-words stage in front of it, it was
  handed to a model instead, which called it a Polish word. Bru found that one, 2026-09-16. Of the
  8,870 pages in a warm cache, **37 were redirect stubs** — every one a word decker had thrown away.
  Seven are exactly this: a Russian word whose `ё` the text prints as `е` (`темный`, `тяжелый`,
  `приемный`, `влюбленный`, `печенка`, `актерский`, `греза`), which is how Russian is ordinarily
  printed. The rest are spellings of every other kind — `East coast` → `East Coast`, `Млечный путь` →
  `Млечный Путь`, `be able` → `be able to`, `как дела?` → `как дела`.

  `_redirects_to` reads the target out of the notice and `_from_redirect` re-reads the page there —
  one hop, since a wiki does not follow a double redirect either. **Unlike the see-box above, the
  title changes**: a see-box is a real section at a real spelling that keeps its definitions
  elsewhere, whereas a redirect is the dictionary saying this spelling is not an entry. For the `ё`
  that is the whole point — `грёза` is the word, and the diaeresis the text dropped is where the
  stress falls: the card reads `[ˈɡrʲɵzə]`. A card fronted `греза` would teach the reader the
  spelling they had just read. One regex, matching the list the notice is written as, which both
  parsers emit; Parsoid also marks it with a `<link rel="mw:PageProp/redirect">` and the mirror's
  legacy parser does not, so that is not what is matched.

  The target may name a section — `解決する` redirects to `解決#Japanese`, the way the English
  Wiktionary files a Japanese `-する` verb under its noun — and the regex took only a bare target,
  so every one of those was dropped and handed to a model that wrote its own gloss
  (`解決すん`, *a colloquial contraction of 'kettei suru'*). The fragment is now matched and
  dropped. Nothing reached these pages before Sudachi: Stanza never kept `解決` and `すん` together.

- **A see-box's namespace links are not its target.** うぐいす's box points at 【鶯】 and also says
  where to *see* the category of kanji read that way, `Category:Japanese kanji read as うぐいす`,
  which `_points_at` took for the spelling, so 鶯 was never read and a model explained the word
  as a swallow. A target with a namespace prefix is skipped; the box then answers with its one
  【 】 entry, and the card reads *short for 鶯色: an olive-green colour*, which is the line's.

  This reaches a lemma whose `ё`-less spelling is a redirect, and only that. An inflected form has
  no redirect of its own — `грёз` is an entry, *genitive plural of грёза*, while `грез` is not a
  title at all — so the form is reached by restoring the mark before the lookup instead, which is
  the rule in [Term extraction](term-extraction.md). The two overlap on the lemmas and neither
  covers the other's words.

- **A stylesheet inlined into a definition is not part of the definition.** MediaWiki puts a
  template's CSS *inside the list item it styles*, so the rendered `<li>` for 男の子 opens with
  `<style>.mw-parser-output .defdate{font-size:smaller}</style>` and the text readers, which took
  every character they were handed, put that CSS on the front of the card ahead of *[from 1711] a
  boy*. Bru found it in a Japanese run, 2026-09-16. Both readers — the tree walk that reads senses
  and the stripper that reads etymologies — now skip `style` and `script` whatever the caller asks
  to skip, since no caller has ever wanted either. It was never a Japanese problem: over 400 cached
  pages sampled at random, 191 carry a stylesheet inside a definition item and 8 had a definition
  change when the fix went in, among them English `main` (*[from 15th c.]*) and the Russian verbs
  that carry object-usage tags — `назвать` read `to call .mw-parser-output .object-usage-tag{…}`
  where it now reads *to call [with accusative ‘someone/something’…]*. The cache holds the raw
  payload, so the fix applies to pages already fetched.

- **A definition that is a Lua or script error is not a definition.** MediaWiki renders a failed
  module into the page, in the place its output would have gone, so a broken template upstream or a
  missing extension on a mirror can put `Lua error in Module:foo at line 63` where a sense belongs.
  A card teaching that is worse than a missing card: it is silent, it is studied, and nothing in the
  run says it happened. `_senses_of` drops such a sense and counts it, and `report()` says how many
  and points at `local-wiktionary.md`, since a mirror missing an extension is the usual reason.
  Measured over 113 languages and 1,192 senses read from the mirror, this has never yet fired —
  every error found sat in a glyph box, a category tree or a conjugation table, all of which the
  sense reader walks past. The guard is there so that the claim does not rest on having audited the
  right hundred languages.

- **Only a timeout is a reason not to cache a page.** The rule that refuses to cache a page whose
  definitions came back as Wiktionary's own error text was matching `Lua error` anywhere in the
  payload. Every Chinese page with a glyph-origin box raised `Lua error in Module:zh-glyph` against
  the mirror, and every Hebrew prefix page raised `Lua error: callParserFunction: function
  "#categoryTree" was not found`. (Both have since been fixed on the mirror itself — see
  [A local Wiktionary](local-wiktionary.md) — which is the better place to fix them, and neither
  fix makes the caching rule any less wrong.) In both the
  definitions were fine, and the page was thrown away and re-fetched on every run — the page cache
  turned off for the two languages this release had just taught decker to read. A named module and a
  missing extension will say the same thing tomorrow, so those pages are kept; the expiry message is
  the only one that means the render gave up, and it is still not written. A page whose *definitions*
  really are error text yields no entries, and a page with no entries was never cached as a gloss.

- **Every recording and every reading of the *lect*, where an entry has lects.** "All, not the
  first" is the rule (below), and a Chinese entry is where it needed qualifying: the English
  Wiktionary writes Chinese as one section with a pronunciation block per variety, so 狗 carries 59
  IPA transcriptions over nine of them — four Mandarin, three Cantonese, twenty-seven Wu — and a
  card built from the section whole showed all of them, plus four Old Chinese reconstructions, on
  one line. `languages.lect_of` says which block a code is taught from (`zh-hans` → Mandarin, `yue`
  → Cantonese, `wuu` → Wu), `_lect_block` slices the section from that variety's name to whichever
  is named next, and the readings and recordings are read from the slice. 狗 goes from 63 readings
  to 4, 人類 to one; Spanish, Japanese and Greek entries are untouched, having no lects to slice.
  A lect name can appear in a definition too — `Wu` is a surname — so slices holding neither a
  reading nor a recording are not the pronunciation, and the section is used whole, which is what
  every language without lects does.

  **Every slice of a lect, not the first**, and it took the real site to find out why. Wikimedia
  names each variety *twice* — once in the collapsed block that carries the recording, again in the
  expanded one that carries the reading — where the mirror names it once. Taking the first match
  gave 狗 its Mandarin recording and none of its four Mandarin readings, and the mirror could never
  have shown it, having no recordings at all. Against Wikimedia now: 狗 taught as `zh-hans` gets 4
  readings and the recording whose filename says `(cmn)`, and taught as `yue` gets 3 readings and
  the one that says `(yue)`; the section carries three recordings in total, the third being Min Nan.
  The same slice does both, because a recording and a reading are the same question asked of the
  same block.

  Reconstructions are dropped everywhere, lects or no lects: `/*Cə.kˤroʔ/` is what 狗 is thought to
  have sounded like three thousand years ago, not how the word in front of the learner is said, and
  the asterisk that says so is the same in every language that reconstructs.

- **The pronunciation of the sense's own etymology block, and of its Pronunciation heading.** Two
  narrowings, found together on one Russian letter. Russian `в` is three words under three numbered
  etymologies — the letter, the preposition, and an abbreviation of `вольт` — and each carries its
  own Pronunciation. Read as one section it gave every sense all of them: the preposition's card
  said `[v] [vʲ] [f] [vɛ] [v] [f] [və] [volʲt]` and played three recordings, one of which is a
  person saying "volt". `Entry` now carries the readings and recordings of the block it was cut
  from, and `Page.ipa_of(sense)` / `Page.audio_of(sense)` answer per sense exactly as
  `etymology_of` and `headword_of` already did. `Page.ipa` survives as the fallback for a block with
  no pronunciation of its own, and it is now read from *above* the first `Etymology 1` — the place a
  page puts the pronunciation its etymologies share — rather than from the whole section, which is
  how `[volʲt]` was reaching everything in the first place.

  The second narrowing is the heading. `я` has one shared pronunciation and, in the pronoun block, a
  usage note saying that "г in the genitive/accusative ending is pronounced as /v/" — prose *about*
  pronunciation, in IPA, and nothing to do with how `я` is said. The reading is now taken from the
  slice that runs from the `Pronunciation` heading to the next heading of any level, so a note, a
  descendants list or a quotation cannot contribute one. A block with no such heading falls back to
  the block whole, which is how a page that writes IPA without a heading for it still works.

  Measured: `в` taught as a preposition gets `[v] [f] [və]` and one recording, the letter gets its
  four readings and three recordings, `вольт` gets `[volʲt]`; `я` gets `[ja]` and loses the `/v/`;
  `мир`, `perro` and 狗 — one block apiece — are unchanged, 狗 keeping its four Mandarin readings.
  The lect slice runs *inside* the Pronunciation section now, which is where it always belonged.

- **What a character has instead of a pronunciation: its readings.** A Japanese `Kanji` block has
  no Pronunciation section, because a kanji is not pronounced — the words written with it are, and
  differently: 決 is *ketsu* in 解決 and *ki-* in 決める. What the block has is a **Readings** list,
  naming each reading and which kind it is, and that list is the whole of what a card about the
  character can honestly say. Bru asked for it on 2026-09-21, having found a `決` card that said
  nothing at all about how the character is read.

  `_character_readings` cuts from the `Readings` heading to the next heading of any level — the
  same cut `_pronunciation` makes — and takes each list item as the page wrote it:

  ```
  Go-on: けち (kechi)
  Kan-on: けつ (ketsu, Jōyō)
  Kun: きまる (kimaru, 決まる, Jōyō)、きめる (kimeru, 決める, Jōyō)、さくる (sakuru, 決る)…
  Nanori: あき (aki)、あきら (akira)、うけ (uke)…          [食, which also has three on'yomi pairs]
  ```

  The page's own wording, kept: which class a reading belongs to is half of what the line teaches —
  an on'yomi is what the character takes in a compound, a kun'yomi what it takes alone — and decker
  has nothing truer to say about it than the entry does. The one thing dropped is the chain of
  historical forms a reading is written back through (`けち (kechi) ← けち (keti, historical) ←
  くゑち (kweti, ancient)`): philology, and three times the length of the answer on a card.

  It hangs off `Entry.readings` for the block that documents the character, and off `Page.readings`
  for the section, which is the one that does the work: 下, 人 and 超 head a `Kanji` block that is
  readings and *no numbered sense*, so there is no entry to hang them on, and 人's shape is glossed
  from Translingual — *Kangxi radical #9* — while the readings the learner needs are two headings
  above it in the Japanese section. A gloss takes them when its term is a single character, whether
  it is a `Symbol:` card or the word card that character also has.

  **Which languages need it.** Measured over the 10,889 pages this machine had cached: 426 Japanese
  blocks carry a `Readings` heading, 89 Ryukyuan ones do — Okinawan, Miyako, Kunigami, Yonaguni,
  Yaeyama, Yoron, Amami, Okinoerabu, Tokunoshima, which the English Wiktionary formats the same way
  — and one Vietnamese one does. Nothing else, and nothing else needs anything: Korean hanja and
  Vietnamese Han tự state their reading in the headword line, which every card already shows
  (`決: Hán Nôm readings: quyết`), and Chinese writes a Pronunciation section per variety, which the
  IPA reader already takes. So the parse is not gated on a language — it reads whatever section it
  was asked for — and Japanese is simply where it fires.

  **And cut to the reading the word in front of the reader uses, from 2026-09-22.** Bru's second
  finding of that morning: `Symbol: 極` came back with all four of its readings and *goku* nowhere
  picked out, though the word that asked for the card was 極楽, *gokuraku*. The list is the honest
  answer when decker does not know which reading is meant — see `teaching-the-script.md` — but here
  the term says which, and a card listing the other three is answering a question the text already
  answered.

  `_as_used` reads it off the page in two steps, both of them the page's own words. A kanji page
  numbers one etymology per word written with the character, each with its own pronunciation, so the
  block whose reading is inside the term's is the one the term reads it as — the test `_as_read`
  already chooses a *sense* by — and that block's headword names the romanization, `• (goku)`. The
  `Readings` line naming the same romanization is the line the deck met, and it is the whole of what
  the card carries: `Go-on: ごく (goku, Jōyō)`, label and all, since which class a reading belongs to
  is half of what the line teaches. The same cut is made for the word card of a single character —
  街 answers `[ɡa̠i]` and has no use for `け`, `かい` and `まち` under it.

  Three things had to be true of the test before it was worth making. **The longest match wins**:
  分 is ぶん in 分析 and ぶ is a reading of it too, so the short one is inside the word as well and
  first-past-the-post named *bu* where the word says *bun*. **A match may not cut a sound in half**:
  the moraic nasal nasalizes the vowel before it, so 分析 is `[bɯ̟̃ɰ̃se̞kʲi]` and ぶ `[bɯ̟]` is
  inside it only if a match is allowed to stop before the combining tilde — which is how *bu* won
  anyway. And **where in the term the character sits decides where in the reading to look**: 一人 is
  *hitori*, 人's own reading as a word is ひと, and ひと is the wrong half of that word. The first
  character of a term is read at the start of it and the last at the end; a character in the middle,
  or one the term writes twice, is looked for anywhere as before.

  Measured over every cached Japanese word of two or more Han characters with a pronunciation —
  383 character-in-a-word questions, each about a page with more than one reading: **185 of them the
  word answers** (48 %), and the reading lines those cards carry fall from 1,521 to 960. Reading the
  185 back: 極楽 gives 極 ごく and 楽 らく, 靴下 gives した and 地下 か, 二人 gives ふた and り, 何者
  なに and もの, 馬鹿 ば and か. The ones that fail fail into the full list — 分析 and 一昨日 both
  do, the first for the nasal and the second because *issakujitsu* ends in the very reading its
  first character would have matched — which is the card decker made before any of this.

- Every recording in the language section is fetched, not the first. A page can list several — `el`
  has one for Spain and one for Colombia — and which one a learner wants is not decker's to guess;
  the design says to fetch all that is available, and taking the first drops the rest silently.
  Wikimedia transcodes each recording into several formats, so the same clip arrives as `.ogg` and
  `.mp3`; those are one recording and not two, and a card holding both would just play it twice.
  They are grouped on everything but the last extension and the `.ogg` kept, being what the source
  is served as. `el` goes from one file to two recordings; `casi`, which has one, stays at one.

- A form-of header stays on the readings under it. Wiktionary writes a form with one reading inline
  — `third-person singular preterite indicative of correr` — and a form with several as a header
  naming the lemma, `inflection of auswandern:`, with the readings listed beneath. Either way the
  card has to say what the word is an inflection *of*, which is the only thing an inflected form
  has to say: `auswanderte` once reached a deck meaning no more than "first/third-person singular
  preterite".

  The rendered page keeps that nesting, so `_senses_of` reads it off the structure. An item whose
  own text ends in a colon is a header rather than a meaning — it is no sense of its own, since as
  a card it would claim the word is all of its readings at once — and its text is prefixed to each
  reading nested under it. The nested list is looked for anywhere beneath the item rather than as a
  direct child, because Wiktionary sometimes puts it inside the item's `dd`.

  It was harder to recover from REST, which flattened the shape into siblings: a header sense
  holding every reading glued together, then each reading alone, without the lemma. `_unflattened`
  put them back by containment — the header sense is literally its first clause followed by every
  child concatenated — and fired on 162 entries of 9,572 before going out with the endpoint. Not a
  German problem either way: Spanish `cuenta`, Portuguese `tormenta`, Catalan `para` and Italian
  `tormenta` all have the shape, since what decides is how many readings a form has, not which
  language it is in.

- Every request to Wikimedia goes through one paced, retrying fetch — API payloads and sound files
  alike — because the rate limit counts them together. Audio used to have a download of its own with
  no pacing and no retry, so one run collected eighteen `429 Your bot is making too many requests`
  and dropped those files silently. The half-second floor between requests and the `Retry-After`
  backoff were already there for pages; audio simply was not using them.

- The User-Agent is built from decker's own installed metadata — `decker/1.0.0
  (https://github.com/NotBru/decker; Build an Anki deck …)` — so the version keeps itself current
  and there is no string to update by hand. The contact is the **homepage**, chosen by that label
  rather than by being first in the list: it is the only way Wikimedia has to reach a human before
  blocking the client, and every install sends the same string, so which URL it is should be a
  decision and not an artefact of the order `[project.urls]` happens to be written in. Any other
  URL stands in only when there is no homepage at all.

- `--wiktionary-host` (or `$DECKER_WIKTIONARY_HOST`) names the origin pages are fetched from, so a
  run can be pointed at a local mirror instead of Wikimedia — see `local-wiktionary.md` for why one
  might want that. The edition still picks the host when no origin is given, since only Wikimedia
  has one host per edition. The flag was **not enough to use a mirror** while senses came from
  `/api/rest_v1/page/definition/`, a Wikimedia service that no MediaWiki serves: pointed at one, a
  mirror answered `action=parse` and 301'd the other, and `fetch` returned nothing. Reading senses
  from the rendered page is what closed that, and the flag is now the whole of the interface.

- **Senses are read from the rendered page, not from the REST endpoint.** `_entries_from_html`
  walks the page the way Wiktionary structures it: a heading names the part of speech, the list
  under it holds one sense per item, a nested list holds its sub-senses, and an example arrives as
  `e-example` plus `e-translation` rather than as one string to cut apart.

- **The REST endpoint is no longer asked for at all**, so a title costs one request rather than two
  and nothing quietly reaches for a second source. There was briefly a fallback to it, for the two
  cached pages — `correr` and `corrió` of 1,742 — whose `parse` request had failed long ago and
  been cached as null. Those were refreshed instead: a fallback for a fault that can no longer
  occur is a path nothing exercises and every reader has to reason about. `_payloads` now fetches
  the rendered page first and returns nothing when it fails, so a failed render is never written.

- This is also what lets a run be pointed at a local mirror, since `/api/rest_v1/page/definition/`
  is a Wikimedia service that no MediaWiki serves.

- What the change is worth, beyond the mirror: **usage notes stop arriving as senses**, because they
  live under their own heading — `la` gave six senses through REST, five of them notes, and gives
  one through the page. Collocation boxes stop arriving too. Form-of senses keep their lemma
  structurally rather than by the containment patch that reassembled them, and the sense text is
  richer, carrying the grammatical labels REST drops.

- Getting there cost four measurements, three of which were wrong, and the record is worth keeping.
  Truncated comparison keys hid that an HTML sense carries a label REST omits. Exact matching
  tripped on CSS leaking into REST text. A "confirmed genuine loss" on `la` turned out to be the
  HTML version being twice as long and strictly better. What finally worked was reading a random
  sample instead of counting one, which found the real bug in a minute: `_tidy` strips trailing
  colons, so the test for "this item is a header, not a sense" could never fire, and every
  `inflection of correr:` was emitted as a sense of its own with its children unattached. One
  character. Uncovered REST senses fell from 203 to 106, and a fresh sample of those is entirely
  usage notes and collocation boxes.

- **The page cache is keyed by title and edition, and the payload records its source.** A mirror
  and Wikimedia render the same entry from the same wikitext, so a cached page is a cached page
  whichever answered; the one thing that differs is audio, which a mirror never has. That was
  briefly a second cache directory per host, and the cost of it was the thing the mirror is for: a
  run pointed at a different source fetched every title again, so a text read once offline and then
  extended online named its whole vocabulary to Wikimedia. Keyed by title, that fetch never
  happens. What the source decides now is only what the page's silence about audio *means*:
  `carries_media` reads it off the payload, and an entry written before the field existed can only
  have come from upstream.

  Bru's call, 2026-09-03, over the earlier keying, which was mine.

- **Silence about audio is reported, both kinds.** Losing every recording and every word happening
  to have none look identical on a card. `[decker] no recordings offered by this source` is printed
  when audio is on, glosses were made, and not one page offered a file — a run wholly against a
  mirror. The mixed run is the one the shared cache makes ordinary, and it gets its own line:
  `[decker] N pages came from a source with no media`, naming how many cards are silent for a
  reason that has nothing to do with their words. `--refresh-pages` recovers the audio, and the doc
  says what it costs — those titles go to Wikimedia.

- A 403 stops the run, and nothing else does. It is the one status that says the *client* was
  refused rather than the resource — a missing page is 404, a rate limit is 429 — and it comes from
  the User-Agent policy or a blocked address, neither of which the next request will escape. So it
  raises `pages.Refused`, the CLI prints what happened, what decker calls itself, and why it
  stopped, and exits 2. Counting these instead would mean scrolling hundreds of them and finishing
  "successfully" with a deck missing most of its glosses.

- A site that is down is waited for, not given up on: a connection that cannot be made, or a 5xx
  the whole site is answering, holds the fetch until the site is back, logged when it goes and
  when it returns ([When a remote stops answering](connectivity.md)). A 429 is waited out for as
  long as it lasts. Every other fetch that gives up is counted and reported: `[decker] 2 fetches
  failed: 1 audio: unreachable, 1 page: HTTP 500`. A page decker cannot get is a gloss it cannot make, and until
  this line existed the only way to notice was to read the deck and find it thin. Silence means
  every fetch that was tried came back. 404 is not counted, being an answer rather than a failure:
  it is how Wiktionary says a title has no entry.

- Incrementality, which the design puts at this stage: given `--previous DECK.apkg`, glosses that
  deck already teaches are left out. A gloss's identity is `gloss_key(surface, definition)`, a hash
  of the pair `_Builder.seen` already keys on — the design's own identity for a gloss, an inflected
  form and a sense. The definition hashed is Wiktionary's, **never the translated text**, so a deck
  built for a speaker of Spanish and one built for a speaker of German agree about what they teach.
  The note GUIDs could not serve: they hash the translated definition, so they differ by mother
  language and cannot be computed before translating.

- The filtering happens **after** disambiguation, not before, and this is the choice most worth
  revisiting. A skipped gloss costs its disambiguation call and saves its translation call, where
  filtering senses before the disambiguator ran would save both. It is not done because the
  disambiguator chooses among a numbered list of senses: remove some and it is answering a
  different question, and quietly changing which senses it picks is a worse price than a call.

- A dependency the previous deck already teaches is simply not depended upon. If `auswandern` is
  known and `auswanderte` is new, the new card carries no dependency, because the ordering it
  encoded — meet the lemma first — has already happened.

- Measured on two Deutsche Welle articles: the second reused 66 of its 165 glosses, 40%. Both were
  built `--no-disambiguate`, so read that as the shape of the saving rather than its size.

- Model answers are cached on disk, under `answers/` beside the pages. Both stages send a prompt
  that is a pure function of what they are asking about, at temperature zero, so the answer is a
  pure function of the request: the same model asked the same thing under the same schema has
  already said what it is going to say. The key is the model, the schema and the prompt together —
  the model because two of them answer differently, the schema because it decides the shape of the
  answer, and the prompt because it carries everything else, so editing a prompt in the source
  invalidates its answers without anyone having to remember to. `--refresh-answers` asks again.

  This was the one part of a run that was not cached, and it was all of the cost: pages, titles and
  recordings were already kept, so a second run of the same text repeated the whole of its wall
  clock and none of its work. It is also what makes an interrupted run cheap — a tunnel that drops
  eight minutes in used to mean starting over.

- Both prompts put their fixed instructions first and the sentence, the surface and the sense
  listing last. Ollama keeps the prefill of a prompt's common prefix between calls and re-reads only
  the tail, and on a laptop's CPU that prefill is nearly the whole cost of a call: the answer is a
  handful of tokens while the listing that precedes it is hundreds. Written the other way round —
  sentence first, instructions after the listing — consecutive calls shared only their opening line
  and re-read everything. A one-line restatement of the task still follows the listing, because
  instructions far from the end of a long prompt are the ones a small model drifts from; it sits
  past the point where the prefix has already diverged, so it costs nothing.

- The model's own reasoning is turned off wherever the client takes the argument. The answer is a
  handful of numbers under a schema, so a chain of thought buys nothing and costs the entire call:
  `qwen3:1.7b` spent 4222 thinking tokens and 80 seconds on a question it answers in 2.3 seconds
  with `think=False`. A client that rejects the argument is asked again without it, and not asked
  with it again for the rest of the run.

- When ollama answers something unusable, or there is no model at all -- no host named and the
  default one never answered -- the gloss keeps every sense and a warning is printed once. A named
  host that cannot be reached, or one that has answered earlier in the run, is waited for instead
  and the question asked again ([When a remote stops answering](connectivity.md)). The design says disambiguation *must* happen, so this is a degraded run,
  not a supported mode; `--no-disambiguate` is the way to ask for it deliberately.

- The occurrence being judged is bracketed in the sentence the model is shown — `—Vaya, ⟨vaya⟩ a
  dormir.` — because a form can occur twice in one sentence as two different words. Unmarked, both
  calls carried the same sentence and the same surface, so the model could not answer differently
  even in principle: the interjection `Vaya` came back carrying the subjunctive sense while the
  actual subjunctive `vaya` had it dropped. Spans come from the tokens the term covers, so a
  multiword token (`del` = `de` + `el`) marks whole.

## One etymology per sense, not one per section

Wiktionary nests a language as **Etymology 1..N -> part of speech -> senses**, and decker read it as
**language -> senses** with a single etymology string beside them. On any page numbering more than
one etymology, every sense got the first.

Spanish `mate` has six. The deck built on 2026-09-14 taught *maté, the drink prepared from yerba
maté* with the line "Borrowed from French mat, mate." — true of Etymology 1, which is the adjective
*matte*; the drink is Etymology 3, "Borrowed from Quechua mati."

Fixed by cutting before walking. `_etymology_blocks` slices the language section at its Etymology
headings; `_entries_in` walks each slice as before and stamps that slice's etymology on the parts of
speech inside it; `Entry` carries it and `Page.etymology_of` answers per sense, by identity, the way
sense pooling already matches them. A section numbering nothing is one block and behaves exactly as
it did.

Two things fell out of it that are worth keeping written down.

- **A numbered etymology is allowed to have no prose at all.** `carga`'s second is a bare heading
  followed straight by its Verb, and `_etymology` searched forward without a bound, walked past the
  heading and returned the *headword line* — so the inflected form was taught as "carga". It now
  stops at the next heading of any level.
- **An entry's own answer is the whole answer, `None` included.** Falling back to the section for a
  block with no prose puts the first etymology back on the card, which is the bug. An inflected form
  has no origin of its own; it has its lemma's, and the lemma has its own card.

Over the 2,671 entry titles of the nine-source corpus: 3,397 parts of speech keep what they had, 237
now carry a different, block-local etymology, 91 correctly carry none, and 15 gained one the section
had not offered. Spot-checked, the changes are right — `alto` the noun and interjection are "Borrowed
from German halt." and not the adjective's Latin *altus*; `aire` has two Spanish nouns and the second
really is "From zorá, named by a zoologist"; every `See the etymology of the corresponding lemma` now
lands on a verb form instead of that form inheriting its lemma's prose.


## Reading ahead of the loop

Fetching and glossing alternated, so one of the two machines a run needs was always idle: decker
asked Wikimedia for a page while the model waited, then asked the model while the network waited. A
cold Japanese build was 97.8 % blocked on those two sockets. `_Ahead` runs two sentences in front of
the gloss loop on two threads, fetching the pages the coming terms will need — their own, and under
`--teach-script` the character pages too — and asking the sense question they will be asked.

**It cannot change a deck, and that is the whole of its design.** It appends no gloss, holds no
index and writes nothing the builder reads back; what it fills is the page cache and the answer
cache, which the loop was going to read anyway. The prompt is built by `Disambiguator.question`, the
one `keep` uses, so the question warmed is the question asked — a prompt differing by a space would
warm nothing and pay for every question twice — and a prompt is a pure function of the page and the
passage, asked at temperature zero. A prefetch that guesses wrong costs one wasted question, which
is why the lookahead is two sentences and the queue is bounded at four: a `--limit-glosses` stop
should not have paid for sentences nobody read.

Three things had to be made safe for a second thread, each of them a line: the page cache writes
beside and moves into place, as the answer cache already did; the run's counters take a lock; and a
question already in flight is waited for rather than asked twice, since a cache file that does not
exist yet cannot dedupe anything. Wikimedia's half stays serialized by the same pacing floor it
always had, which is what that server counts.

The numbers are in [The benchmark](benchmark.md): 403 s to 232 s on the same cold workload, and a
byte-identical deck given the same caches and seed.

## Licensing

- Wiktionary's text is CC BY-SA 4.0, and a gloss quotes it whole — definitions, examples,
  etymologies. The Markdown document therefore ends with a line naming Wiktionary and the licence,
  which together with the per-gloss entry links is the attribution the licence asks for. Deck
  construction carries the same line in the deck's description and on the back of every card — see
  [deck building](deck-building.md#anki-output), since a document is read whole and a deck one card
  at a time.

- Attribution names Wikimedia whichever origin answered. `WIKTIONARY_HOME` and the per-entry links
  are built from the edition, never from `--wiktionary-host`, so a deck built entirely against a
  local mirror still credits `en.wiktionary.org` and links a reader there. That is the right
  target: the text is Wikimedia's wherever it was served from, and a link to `localhost:8080` would
  credit nobody and resolve for no one.

- Pronunciation files are licensed one by one on Commons, and decker keeps only the URL and the
  cached path — not the recording's author or licence. Nothing is redistributed while the file sits
  in `~/.cache/decker`, so v1 leaves this alone deliberately; a deck meant to be shared would have
  to collect the per-file credit from Commons first.

## Known gaps

- IPA is collected from the whole language section. This was written up as a defect, citing `el`
  coming back with `/el/ [el] /eɾ/ /e/ /a/`; reading the page says otherwise. Four of those five are
  `el`'s own — the main reading, then Andalusian `/eɾ/` and rapid-speech `/e/`, both under `el`'s
  single Pronunciation heading. Only `/a/` comes from further down the page. Dialectal variants are
  the word's, and a learner is better off seeing them, so the readings stay as they are. What is
  genuinely wrong is small and structural: a page whose language section holds several etymologies
  pools their pronunciation blocks. The etymologies themselves no longer pool — see above, the
  section is cut by sub-heading before it is walked — and the same cut would serve the readings.
  Still open, and now a smaller job than it was.

- Audio was also written up as fetching a neighbouring entry's recording — the `el` gloss handed a
  recording of `él`. That is wrong too. The file Wiktionary lists under `el`'s own *Audio (Spain)*
  is merely *named* after `él` upstream, presumably by whoever uploaded it. Decker was reading the
  right section; a filename check would have rejected the file Wiktionary itself offers. Both claims
  came from reading the code and the filename rather than the page, which is the mistake worth
  remembering here.

- Usage notes arrived among the definitions while senses came from the REST payload, so `la` came
  back with sentences like *Used primarily in Spain* as if they were senses — six senses, five of
  them notes. Accepted for v1 at the time, since that payload marked them in no way at all, and
  **closed** by reading senses from the rendered page instead: a usage note lives under its own
  heading there, and a heading that does not name a part of speech opens no sense list.

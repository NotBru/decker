# Ten languages, one mother tongue

`docs/instructions/` is the source of truth: where this contradicts the design, the design wins and
this document is what needs correcting. Like `deck-growth.md`, this records a measurement, not a
decision — what decker makes of ten languages taught to a speaker of English, and which parts of it
stop working where.

## What was run

One sample of Wikipedia prose per language, the whole pipeline over it, cards built for a speaker of
English (so nothing was translated and the model was spent on sense disambiguation and rules alone).
Pages came from the local mirror; `gemma4:latest` over the tunnel; audio off; every language started
from an empty rule book, so "rules written" means the same thing in all ten.

The samples are the lead sections of the same four articles in each language — *Cinderella*, *Dog*,
*Rain*, *Bread* — cut to about 2,500 characters, or about 900 for Japanese and Chinese, whose
characters carry several times as much. Same content, same register, same size, everywhere. Irish
needed eight more articles to reach the budget, because Irish Wikipedia's articles are two sentences
long; its sample therefore covers different topics from the rest, which is itself the first finding.

Ten languages: two Germanic baselines (German, Dutch), the Spanish the growth experiment used, two
with their own script and heavy inflection (Greek, Hebrew), two agglutinative (Hungarian, Turkish),
one Celtic with initial mutations (Irish), and two that put no spaces between words (Japanese,
Chinese).

## The table

| language | sentences | terms | coverage | glosses | word / concept / rule | cards | culled | calls | wall |
|---|---|---|---|---|---|---|---|---|---|
| Spanish | 15 | 323 | 94 % | 281 | 241 / 28 / 12 | 522 | 10 | 363 | 512 s |
| German | 22 | 312 | 95 % | 295 | 250 / 31 / 14 | 545 | 5 | 420 | 545 s |
| Dutch | 24 | 316 | **99 %** | 288 | 256 / 26 / 6 | 544 | 16 | 370 | 570 s |
| Greek | 17 | 291 | 98 % | 290 | 245 / 23 / **22** | 535 | 2 | 360 | 464 s |
| Hungarian | 19 | 234 | 91 % | 220 | 193 / 20 / 7 | 413 | 2 | 177 | 371 s |
| Turkish | 22 | 309 | 94 % | 288 | 255 / 24 / 9 | 543 | 0 | 261 | 669 s |
| Irish | 35 | 337 | 98 % | 298 | 262 / 27 / 9 | 560 | 1 | 366 | 666 s |
| Hebrew | 25 | 333 | 99 % | 244 | 217 / 26 / 1 | 461 | 3 | 274 | 296 s |
| Japanese | 18 | 308 | 90 % | 200 | 193 / 7 / **0** | 393 | 0 | 241 | 608 s |
| Chinese | 19 | 383 | **82 %** | 240 | 231 / 9 / **0** | 471 | 0 | 263 | 895 s |

"coverage" is the share of term occurrences for which the English Wiktionary had an entry in that
language. `languages-coverage.png` and `languages-cards.png` draw the first and the last two
columns; `languages.csv` has the rest.

## The pipeline runs everywhere. That is the headline and it is not the interesting part.

Every one of the ten produced a deck, in its own script, with dependencies, examples and readings
intact, at roughly the same cost per term — 1.2 to 1.8 cards per term occurrence. Nothing crashed,
nothing needed a flag, and the term extractor's job (find the words, find their entries) is done
well above 90 % everywhere except Chinese. The English Wiktionary really does carry every language,
and reading it through one mirror really does work for all of them.

What varies is *which stage* degrades, and it degrades differently in each.

## Where it breaks, worst first

The first four of these have since been acted on — what each one turned into is at the end of this
document, under [What was done about it](#what-was-done-about-it). They are left as they were
measured, because what the fixes are worth is only legible against them.

### Chinese is off by one word, twice

**decker asks for the wrong language section.** A language is named by Stanza's table, which agrees
with Wiktionary's section headings almost everywhere — and not here: Stanza calls `zh-hans`
*Simplified Chinese*, and the page 狗 heads its section `Chinese`. Unpatched, every Chinese lookup
returns nothing and the deck is empty. The run above patched the name in the harness; the fix
belongs in the design's hands, and it is one entry in a table.

**Simplified entries carry no senses.** With the name fixed, 82 % coverage is still the worst of the
ten, and the misses are ordinary high-frequency words — 之间, 人类, 习得. They are not absent:

```
人类 -> 0 senses      人類 -> 1 sense   (collective) humanity; humans; humankind
之间 -> 0 senses      之間 -> 2 senses  between
习得 -> 0 senses      習得 -> 2 senses  to acquire (a skill); to learn (a subject)
```

The English Wiktionary writes the simplified entry as a soft redirect to the traditional one, and
decker's sense reader sees an entry with no definitions rather than a pointer to follow. The sample
was mixed script, which is why 82 % and not 40 %. A wholly simplified text would lose most of itself.

### Hebrew teaches the alphabet instead of the grammar

Coverage is 99 %, which flatters it. Stanza's Hebrew tokenizer splits the clitic prefixes off, as it
should — `לכל` becomes `ל` + `כל` — and decker then looks up `ל`, whose Wiktionary page offers both
the preposition and the name of the letter. The disambiguator picked the letter, five times over:

```
ל : Lamed: the twelfth letter of the Hebrew alphabet, after כ and before מ.
ב : Bet, beth, vet: the second letter of the Hebrew alphabet…
ה : He, hei: the fifth letter…
ו : Vav, waw: the sixth letter…
ש : Shin or sin: the twenty-first letter…
```

Those five prefixes are among the most frequent things in any Hebrew text, so they sit near the
front of the deck, and each of them teaches the wrong thing. The two-letter function words around
them — של, את, על, עם, יש — are all correct, so this is not a Hebrew problem in general: it is
specifically that a one-letter token has a letter-name sense competing with its grammatical one, and
that a sentence-context prompt gives the model little to go on. 33 of the 217 Hebrew word cards are
one or two characters.

### Japanese never reaches the terminology, so it never reaches the rules

Seven concept cards and no rules at all, where Greek got 23 and 22. Japanese entries on the English
Wiktionary do not write their inflections as glossary-linked form-of lines, so `bundle_of` sees no
concepts, and with no feature bundle the rules stage stands down by construction. Japanese is not an
uninflected language — 広く, 早く and あり are all in the missed list — so this is a stage that is
switched off by the shape of the source rather than by the shape of the language. Chinese's zero is
the honest kind: there is nothing to inflect.

The Japanese misses also include the full-width punctuation `（ ） ：` and the Latin words inside the
article, which is the extractor offering the definer things that were never going to be entries.

### The model imports gender into languages that have none

The rule prose is the weakest link everywhere, and in the agglutinative languages it fails in a way
that is easy to name. Hungarian and Turkish have no grammatical gender at all, and the rules written
for them say:

- Turkish — "For **feminine** nouns, add the ending -ın to form the genitive singular."
- Turkish — "For **feminine** nouns, add the suffix -si to form the third-person singular possessive."
- Hungarian — "For **masculine** nouns ending in a consonant, the nominative plural is formed by adding -ek."
- Hungarian — "For nouns that are **masculine**, the singular form is created by adding -a."

The endings are often right; the class the rule is stated over is invented. And Turkish vowel
harmony — the one thing a learner most needs stated — is named in exactly one of the nine rules
("adding the suffix -lar or -ler"), and never explained. The same failure in milder form shows up
everywhere, including Spanish ("for masculine nouns ending in a consonant, the diminutive is formed
by adding -illo", of `gallo` → `gallito`, which is wrong about both).

This is the ceiling described in `docs/execution/morphological-rules.md`, seen across ten languages:
the stage's *economics* work (`deck-growth.md`), and its *prose* is only as good as the model.

### Irish works, and is the pleasant surprise

98 % coverage, the initial mutations resolved (`chos` glossed as "lenited form of cos"), the copula
`is` found, and the verbal-noun and autonomous-form terminology coming through as concept cards. The
only thing Irish lacks is text: its Wikipedia gave 767 characters across four articles where every
other language gave 2,500, so the sample had to be assembled from twelve. For a small-Wikipedia
language the bottleneck is the source, not decker.

### Greek is where the rules stage earns the most

22 rule cards from 291 terms — the highest of the ten — because Greek writes its inflections exactly
the way the stage wants: form-of lines with linked terminology, over a language with a lot of
inflection. The descriptions have the usual accuracy problem, but the *shape* of the output is right,
and Greek is the language in this set where a rules-aware deck would differ most from a word-only one.

## What was done about it

Bru's call, 2026-09-14: do the first two, try the third and the fourth, explain the fifth. The table
above is the measurement *before* any of it and stays that way; this is what each one turned into.

1. **Chinese is named `Chinese`.** `languages.section_of` is a table of five entries — the three
   Chinese codes, and `nb`/`no`, where Stanza says *Norwegian* and Wiktionary heads *Norwegian
   Bokmål* — consulted where a Wiktionary section heading is wanted and nowhere else. What a prompt
   calls the language is still Stanza's `name_of`: a text in `zh-hans` really is in Simplified
   Chinese, and a model told so knows something true about it. The harness patch is gone.

2. **A simplified entry's pointer is followed.** How, in
   [Definition fetching](definition-fetching.md): the `zh-see` box is read inside the language
   section, the section is re-read at the title after the word "see", one hop, and the title stays
   the spelling the *text* used — 人类 is what the reader met, 人類 is only where the dictionary
   keeps the definitions. The same Chinese sample, with nothing else changed:

   | | terms | coverage | glosses | word / concept / rule |
   |---|---|---|---|---|
   | the survey's run | 383 | 82 % | 240 | 231 / 9 / 0 |
   | pointer followed | 383 | **99 %** | **302** | 288 / 14 / 0 |

   The four occurrences still without an entry are *Canis lupus*, *Canis lupus familiaris*,
   *Cendrillon* and *Cenerentola*, which are not Chinese — finding 5, and all that is left of the
   worst column in the table.

   A third thing had to change for this to be worth anything. Decker refused to cache any page whose
   payload carried the words `Lua error`, and the mirror raises a deterministic one on every Chinese
   page with a glyph box (`Module:zh-glyph`) and on every Hebrew prefix page (a missing
   `#categoryTree`). Those pages were re-fetched on every run, with the definitions intact each time.
   Only the timeout message counts as the render giving up now.

3. **The part-of-speech hint was tried, and it is not what was wrong.** The parse's UD tag is now in
   the disambiguation prompt as a hint, which is the finding as written — and on its own it made
   Hebrew slightly *worse*: told to prefer an adposition among senses none of which is one, the
   model hedged and kept more wrong cards rather than fewer (the numeral 2, a lexicographic
   initialism).

   The reason is that the preposition is not on the page. `ל` is a page about the *letter* — Lamed,
   and two noun senses — and the preposition is at `ל־`, with a maqaf, as it is for all seven
   prefixes the sample uses. So a second fix, which is the one that mattered: a clitic — a word the
   tokenizer split off a multiword token, and not its last — is also looked up under the bound
   spelling, and the two pages' senses are pooled the way `Bueno` and `bueno` are.

   | Hebrew, `gemma4:latest` | cards for the seven prefixes | from the prefix's own entry | a letter of the alphabet | glosses |
   |---|---|---|---|---|
   | the survey's run | 9 | **0** | 7 | 264 |
   | hint alone | 12 | **0** | 6 | 270 |
   | bound title alone | 12 | **9** | 3 | 262 |
   | both, which ships | 11 | **8** | 3 | 265 |

   ל now teaches *to*, ב *in*, ה the definite article, ו *and*, ש *introduces a subordinate clause*,
   מ *from*, כ *like, as*. Three keep the letter's card alongside, which is a sense the page has.
   62 of the sample's 333 term occurrences are one of these seven.

   The hint stays even though it does nothing for this model, because it does something for the
   default one: `qwen3.5:4b` answers the bound title alone with 39 cards for those seven words and
   302 glosses, and with the hint as well with 19 and 271. It also takes `gemma4:latest` from 7/9 to
   8/9 on the Spanish nine-check benchmark. Asked of four models, no model gets a single prefix
   right without the title — `qwen3:14b` included, which is the plainest evidence that a bigger
   model was never the answer here. [Model backends](model-backends.md) has that table.

4. **The rules prompt is told which categories the language has — and it is not a general fix.**
   Not by a table but by the parse: Stanza marks the categories a language inflects for on every word
   it reads, term extraction now carries them, and a category marked nowhere in the whole text is one
   the language does not have. Six are pervasive enough to say that about — gender, number, case,
   person, tense, definiteness — and a language that marks all six is told nothing at all, so the
   prompt is unchanged for every European language here. The reasoning, and why *mood* was tried and
   dropped, is in [Morphological rules](morphological-rules.md).

   | `gemma4:latest` | rules written | stated over a gender the language lacks |
   |---|---|---|
   | Turkish, with the inventory | 13 | **0** |
   | Turkish, without | 11 | 2 |
   | Hungarian, with the inventory | 7 | **0** |
   | Hungarian, without | 7 | 3 |

   The arm without it reproduces this document's own quotations word for word — "For feminine nouns,
   add the ending -ın to form the genitive singular" — and the arm with it writes the same rule as
   "For nouns, add the suffix -ın to form the genitive singular".

   Asked of four models, though, the paragraph is not the clean win those four rows suggest, and the
   *wording* turned out to be most of it. Its first version ended "an ending that applies to feminine
   nouns cannot be the rule in a language without gender" — and `gemma3:4b` then wrote four gendered
   Turkish rules where it had written none without the paragraph, `qwen3:14b` one where it had
   written none. The sentence telling a model not to say *feminine nouns* was the only place in the
   prompt those words appeared. Rewritten to say the same thing without naming a class, the totals
   over eight model-language pairs are **8 gendered rules with no paragraph, 7 with the first
   wording, 5 with the one that ships** — and zero for the model the survey ran on. `qwen3.5:4b`,
   the default, never writes one under any arm.

5. **Dropping punctuation and foreign-script runs was explained, not done.** The measurement says
   it is a fix to the *report*, not to the deck. A term with no entry never reaches the model:
   definition fetching prints one line to stderr and moves on, so these cost no call, no card and no
   study time. What they cost is a title lookup, one page fetch where the word is a title in some
   other language (cached afterwards), and a lower coverage figure in the table above.

   What is actually in the misses, over the survey's own runs:

   | | distinct misses | Latin-script words and numerals | full-width punctuation | the rest |
   |---|---|---|---|---|
   | Japanese | 20 | 10 | 3 | 7 |
   | Chinese, after finding 2 | 4 | 4 | 0 | 0 |
   | Spanish | 18 | 17 | 0 | 1 |
   | Hebrew | 5 | 4 | 0 | 1 |

   Two things follow. **"Foreign-script run" only names the problem where the language has its own
   script**: Spanish's misses are the identical phenomenon — Perrault, Grimm, Basile, Cendrillon,
   `11`, `900` — in the same script as the text, so a script rule would fix two languages of ten.
   The parse names them better than the script does: they are `PROPN` and `NUM`, and every term now
   carries its tag. **Punctuation is the clean half**: `PUNCT` tokens are already dropped, and the
   three that got through are full-width characters Stanza's Japanese model tags as something else,
   so "drop a token that is entirely Unicode punctuation whatever the parse calls it" is one line
   and cannot be wrong.

   **And a proper noun with an entry is taught.** Bru's call, 2026-09-15, closing the question this
   document was going to leave open. A country is not the same word in the next language over and
   there is no way to infer which — 日本, `Japón`, `Alemania`, 中國, 歐洲 — so an exonym is
   vocabulary in exactly the sense the deck exists for. The worst case of a redundant name card is
   also bounded by the thing that schedules it: one *good* and Anki does not show it again this
   year. That argument generalizes past this question, which is why it is written down here: the
   cost of a card the learner already knows is one review, not a place in the deck.

   So no `PROPN` filter and no `NUM` filter. What the tags are for is what they are already used
   for — the parse's reading of an occurrence, in the disambiguation prompt — and the only filter
   this finding leaves standing is the punctuation one.

## Caveats

- One sample per language, 2,500 characters, one register (Wikipedia's). Coverage figures are for
  encyclopedic prose and would move on narrative or dialogue.
- The table was measured with one model, `gemma4:latest`. Four models have since been asked the same
  two questions, and the answers differ enough to matter — `qwen3.5:4b` never invents a gender at
  all, `gemma3:4b` keeps four times as many senses for a pooled page. The table is in
  [Model backends](model-backends.md); read the ten-language table above as one model's run.
- The Irish sample covers different topics from the other nine.
- Chinese ran with a harness patch that the package did not have at the time. Finding 1 is now in
  the package, so the row is what decker does; the coverage figure is not, and finding 2 says what
  it became.

# Term extraction: implementation choices

Written by an AI agent, not by hand. It records the choices taken while implementing v1's term
extraction, which refine [the v1 design](../instructions/v1/design.md) without changing its shape.
The design documents remain the source of truth: where one of these contradicts them, the design
wins and the code is wrong.

## Titles

- Titles come from the English Wiktionary (`--edition` overrides). It carries entries for every
  language, including the ones the target's own edition lacks — `de color`, `en silencio`,
  `dar gusto` — and it is where the glosses come from anyway.
- The dump those titles come from is a flat list of page names, 9.0M of them for English, with no
  language attached to any of them, so a token is matched against every language at once:
  `Lo lamentó` matches `Lo`, a Chinese surname, and Stanza's mislemmatisation of `animé` to
  `animer` lands on a French entry. Reading the target's own edition would shrink the list — 950k
  titles for Spanish — but not fix this: a title there carries no language either, so the same
  kind of false hit survives. Filtering by language needs a source that keeps the language
  section, such as wiktextract's per-entry JSON, which would supply the glosses too. That trades
  Wikimedia's own dump for a third party's, so it is a v2 question.
- A single-word title's tree is a single node, so it needs no parse: it is matched by spelling.
  Only multi-word titles are parsed into trees. Their parses are cached on disk, as are the dumps.
  A title is multi-word by its spaces — except in a language written without them, where a title
  the parser cuts into several tokens is parsed too; see *Languages written without spaces* below.
- The index is built for the text at hand: a title whose words the text cannot spell cannot match,
  so it is never parsed. `decker index` (or `extract --whole-index`) builds the whole index that
  the design's one-time setup describes instead. Both produce the same terms, but for one thing:
  the whole index leaves an unspaced compound single-word, so `事務所` is found only by a run over
  a text.

## Matching

- The pattern side is matched by the spelling the title is written with; the source side offers
  every spelling a token can be looked up under: surface form, lemma, lower case when the capital
  is only the position's (below), and, in languages that write separable verbs joined (de, nl, af, hu),
  the particle glued to the verb, so `siehst ... aus` matches `aussehen` and covers both tokens.
  Both the inflected entry and the lemma entry therefore match. They are not two terms: matches
  are grouped by the tokens they cover, so one occurrence is one term — carrying the inflected form
  the design asks for, its lemma, and every entry it matched, form's page first. Definition
  fetching picks from those.

  Lemmatizing the title side too — the literal reading of the design — would instead map the entry
  `corrió` onto every occurrence of `correr`.

  The cost of offering the sentence-initial lower case is noise: a sentence starting with `He`
  yields the helium entry alongside the pronoun, for sense disambiguation to throw away later.

- A sentence-initial capital may or may not be part of the term, and term extraction does not
  decide. Both spellings are carried as the form's own (`Term.spellings`), and definition fetching
  pools the entries they reach into a single choice for sense disambiguation. Comparing against the
  raw surface alone had also cost `Vivía` the `vivía` entry, and with it the inflection, the form-of
  definition and the dependency edge.

  A capital anywhere else is the word's own. Offering the lower-case spelling for every capital was
  tried and reverted: it is the sentence start that makes a capital suspect, and lowering all of them
  buys a few fixes with proper-noun noise everywhere else.

- **A line start counts as a sentence start when the parser could not tell.** Lyrics and captions are
  written a line at a time and punctuated barely or not at all, so Stanza reads five lines of a song
  as one sentence — and every line but the first then keeps a capital that belongs to the line. The
  word is looked up capitalised only, finds nothing, and the occurrence falls back to its lemma's
  entry: `Упавший` never reached `упавший` (*past active perfective participle of упасть*) and was
  glossed from `упасть` instead, which is a different word with a different card. Bru found the card
  in a deck built from lyrics, 2026-09-16.

  So `positional_capital_ids` now marks the first word of every line as well as the first word of the
  sentence, punctuation at the head of a line passed over as at the head of a sentence, and reads the
  break off the sentence's own text because that is the one thing the tokens do not carry. It is not
  the reverted rule: a capital *inside* a line is still the word's own, which is what keeps German's
  nouns and everybody's proper nouns out of it — and captions proper are unaffected either way, since
  `subtitles.py` folds cues into running prose with no line breaks left in it.

  What it recovers, counted against the deck that showed the bug: of its 641 cards fronted with a
  form their entry did not match, 42 have a page for the form itself and 29 of those are reachable
  only in lower case. The other 579 are forms Wiktionary has no page for at all, where the lemma's
  entry is the right card and the fix is the one in `definition-fetching.md` — the front now says so.

- **A mark the text leaves off and the dictionary keeps is put back before the lookup.** Russian
  prints `ё` as `е` nearly everywhere — `грез`, `темный`, `елка`, `звезды` — and the English
  Wiktionary titles those entries `грёз`, `тёмный`, `ёлка`, `звёзды`. Neither side is wrong, so
  there is nothing here for the unknown-words model to judge: asked what `грез` is, `qwen3.5:4b`
  answers that it is a Russian word meaning *dreams*, which is true, and leaves it without its
  entry. It is a computation, and `languages.respellings` is it — a fourth table beside `_SECTIONS`,
  `_JOINERS` and `_LECTS`, with one entry, `ru`.

  Every combination of the marks is offered, since a word can drop two (`трехколесный` for
  `трёхколёсный`), and the candidates are generated blind: they are looked up against the title
  index like any other spelling, and one that is not a title costs a set membership test and
  vanishes. A word carrying more than four `е` is left alone — Russian words with five `е` exist
  and words with five `ё` do not.

  A candidate that *is* a title becomes one of the form's own spellings (`Term.respelled`), so the
  card is fronted with it. `грез` in `Это мир моих грез` now reaches `грёз` — *genitive plural of
  грёза* — where before it reached no entry at all and went to the model, which called it a Polish
  word. Four sentences of ordinary Russian gain thirteen cards this way: `тёмный`, `ёлка`, `ёлку`,
  `ребёнок`, `звёзды`, `всё`, `ещё`, `её`, `слёзы`, `грёзы`, `приёмный`, `актёрский`, `лётчиком`.

  The vocabulary the index is filtered by has to carry the candidates too, or the scan throws away
  the very titles they were generated to reach. Over those four sentences it doubles — 58 spellings
  to 112 — and the index grows from 60 single-word titles to 76, over the same 4.1-second pass of
  the dump. The pass is the cost, and it is unchanged.

- Joining the particle is restricted to languages that write separable verbs as one word.
  Ungated, English produced the archaic entry `upgive` from `gave ... up`.

- Matches covering nothing but punctuation are dropped, and a term the sentence uses twice in the
  same form is reported once.

## Japanese, and languages written without spaces

- **Japanese is cut by Sudachi, not by Stanza.** Stanza still tags and parses it; Sudachi decides
  where its words begin and end and what each one's dictionary form is. Stanza's Japanese
  tokenizer and lemmatizer were trained on edited prose, and a manga's speech is not that. Over
  the first Gokurakugai volume, 2026-10-10:

  | in the text | Stanza's lemma | Sudachi's |
  |---|---|---|
  | `撮られん` | `取る` | `撮る` |
  | `太んなくて` | `太ぶ` | `太る` |
  | `減んない` | `減む` | `減る` |
  | `遭うまで` | `会う` | `遭う` |
  | `もータオさん` | `もーター` (*motor*) | `もー`, `タオ` |
  | `他人事` | `他` + `人事` | `他人事` |
  | `いんなら` | `言う` | `いむ` — both wrong |
  | `長ェな` | `長ェ`, unparsed | `長` + `ェ` — both wrong |

  A wrong lemma is the one error nothing downstream can undo: the model is shown the senses of
  `取る` and chooses among them. The last two rows are what is left, and they are the contracted
  forms a dictionary has no entry for; normalising them before the cut is the next step, not this
  one.

- **Decker registers its own Sudachi tokenizer with Stanza** rather than using the `sudachipy`
  variant Stanza ships. That one cuts at Sudachi's longest units and ends a sentence only at
  `。！？`, and a manga's bubbles are separated by blank lines and rarely punctuated: the whole
  volume would have been one sentence. Decker's ends a sentence at a blank line or at a closing
  mark (`。！？!?‼⁉`, with a closing bracket or a variation selector kept on the sentence it
  follows), and hands Sudachi the text a line at a time, since it refuses inputs over 49,149 bytes.

- **The shortest unit (split mode A), and the core dictionary.** Long units (mode C) make
  `事務所` one token, but also make a compound Wiktionary has no page for one token with no entry
  at all; short units keep the pieces, and the title index puts a compound back together wherever a
  page exists (below). `極楽街` stays `極楽` + `街`, which is the most the dictionary can teach.
  The full dictionary was tried alongside and cut these lines the same way; core is Stanza's
  default and a third of the download.

- **Lemmas are Sudachi's dictionary form, put in after Stanza has run.** Stanza's lemmatizer still
  runs — the parser was trained with its output there — and its answers are then replaced span for
  span. Sudachi is run over the text twice for that, which is milliseconds and the same cut both
  times. Its normalised form is not used: it would turn `遭う` back into `会う`.

- **A symbol is the dictionary's to know.** Stanza's tagger, handed Sudachi's cut, tagged `！` a
  noun, and Sudachi's dictionary form for it is a half-width `!` the text never wrote, which is a
  Wiktionary title. A morpheme Sudachi calls `補助記号`, or one with no letter or digit in it — it
  calls `‼︎` a common noun — keeps its own text as its lemma and is tagged `PUNCT`.

- **In a language written without spaces, a title is a phrase when the text spells it across
  adjacent tokens.** Single-word titles are matched by spelling against one token, and a title was
  single-word by having no space; in Japanese no title has one, so `事務所`, `他人事` and
  `行方不明` — two tokens each in the text — were never reachable, and their parts were glossed
  instead: `事務` *clerical work* and `所` *place* for an office. The index now collects every run
  of two to eight adjacent tokens as the text writes it, and with its last token in its lemma
  (`出回ったら` is also `出回る`); a title among those that no single token spells is parsed like a
  multi-word one. Stanza cuts a title alone the way it cuts it in a sentence, so the tree matches.
  On six lines of the volume that was 52 single-word titles and 6 phrases parsed, and the terms
  came out as `事務所`, `行方不明者`, `他人事`, `出回る` and `週刊誌`.

  Two things go with it. A phrase there must cover adjacent tokens, since an unspaced title is a
  word and its pieces are written side by side; elsewhere `gave himself up` still matches
  `give up`. And the phrase is written without spaces, with only its last token's lemma — the end
  is where a compound inflects, and every token's lemma would make `出回る` into `出る回る`. A marked
  occurrence's adjacent spans are bracketed as one, so the model is shown `⟨出て⟩` and not
  `⟨出⟩⟨て⟩`.

  Chinese is in the same set for the same reason, but has not been run since.

## Known gaps

All four below are **accepted for v1**, in the order they should be taken up afterwards. The
design's subtree identification is implemented and works; these are places where Stanza's parse and
Wiktionary's titles disagree about what a word is, and each needs new machinery rather than a fix.
Foreign names come first: it is the only one that puts a confidently wrong card in front of a
learner rather than quietly dropping a right one, and any German news text will trip it. The
multiword-token one is second: it has a known starting point (`word.parent`), it affects the
commonest words in three of decker's languages, and `del` and `al` will occur in almost any Spanish
text. The context-dependent parse is third and open-ended. Hungarian is last, and may not be
reachable within this design at all — both halves fail for unrelated reasons.

- A foreign name embedded in the source is taken apart, and whichever of its words happen to exist
  in the target language are glossed as though they were it. `Trans-Caspian Enterprise Fund`, in
  a German article, produced a card teaching `Trans` as *Tran* — whale oil — and another teaching
  `Fund` as a find, when the text means an English company name. `Caspian` and `Enterprise` were
  dropped safely, and only because no German entry exists for them; `Sokolov`, `IJS`, `52`, `21`
  and `200` were dropped the same way, each with a line on stderr. So the safety here is an
  accident of coverage, not a rule: a fragment survives exactly when it collides with a real word
  of the target language, which is also exactly when the card it makes is most convincing and most
  wrong.

  This is the worst-behaved gap of the four, because the others lose a term and this one invents
  one. A fix has to decide that a span is a name in a foreign language before glossing its parts.
  Stanza's NER, or simply refusing to gloss a word inside a capitalised multi-word run that also
  contains an unglossable word, would both be starting points; neither is v1 work.

- An expression whose parse in context differs from its parse in isolation is missed. Alone,
  `de cuando en cuando` nests: the first `cuando` is the root and the second hangs off it as an
  `advmod`. Inside `Lo visito de cuando en cuando`, the nesting flattens — both `cuando`s become
  sibling `advmod` children of `visito` — so the pattern's inner edge has nothing to match and the
  entry is lost.

- Titles that Stanza's multiword-token expansion takes apart are unreachable. Labels are built from
  the syntactic words, so `Vengo del cine` offers `de` and `el` but never `del`, and the `del` page
  goes unmatched; `al`, French `au` and `du` are the same shape. The reverse shows up in output too:
  a term covering several words of one token would be printed with the spaces the source lacks.
  Stanza keeps the unexpanded token on `word.parent`, which is where a fix would start.

- `hu` is in the joined-particle set but never fires. Separated, Stanza labels the preverb
  `compound:preverb`, not the `compound:prt` the code matches on, so `Nem nézem meg a filmet` never
  reaches `megnéz`. Joined, `Megnézem` lemmatizes to `meg+néz`, with a literal `+` that no title
  carries. Both `megnéz` and `megnézem` are real pages, so both halves are missed.

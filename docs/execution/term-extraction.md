# Term extraction: implementation choices

Written by an AI agent, not by hand. It records the choices taken while implementing v1's term
extraction, which refine [the v1 design](../instructions/v1-design.md) without changing its shape.
The design documents remain the source of truth: where one of these contradicts them, the design
wins and the code is wrong.

## Titles

- Titles come from the English Wiktionary (`--edition` overrides). It carries entries for every
  language, including the ones the target's own edition lacks — `de color`, `en silencio`,
  `dar gusto` — and it is where the glosses v1 will fetch come from anyway.
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
- The index is built for the text at hand: a title whose words the text cannot spell cannot match,
  so it is never parsed. `decker index` (or `extract --whole-index`) builds the whole index that
  the design's one-time setup describes instead. Both produce the same terms.

## Matching

- The pattern side is matched by the spelling the title is written with; the source side offers
  every spelling a token can be looked up under: surface form, lemma, lower case when the capital
  is only the sentence start, and, in languages that write separable verbs joined (de, nl, af, hu),
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

- Joining the particle is restricted to languages that write separable verbs as one word.
  Ungated, English produced the archaic entry `upgive` from `gave ... up`.

- Matches covering nothing but punctuation are dropped, and a term the sentence uses twice in the
  same form is reported once.

## Known gaps

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

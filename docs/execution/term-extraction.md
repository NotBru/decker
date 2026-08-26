# Term extraction: implementation choices

Written by an AI agent, not by hand. It records the choices taken while implementing v1's term
extraction, which refine [the v1 design](../instructions/v1-design.md) without changing its shape.
The design documents remain the source of truth: where one of these contradicts them, the design
wins and the code is wrong.

## Titles

- The English Wiktionary (`--edition` overrides) has entries for every language, so a token is
  matched against all of them at once: `Lo lamentó` matches `Lo`, a Chinese surname, and Stanza's
  mislemmatisation of `animé` to `animer` lands on a French entry. Reading the target language's
  own edition would cut that noise, at the cost of the entries only English has — `de color`,
  `en silencio`, `dar gusto` — and of the glosses v1 will fetch from English anyway.
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

- Joining the particle is restricted to languages that write separable verbs as one word.
  Ungated, English produced the archaic entry `upgive` from `gave ... up`.

- Matches covering nothing but punctuation are dropped, and a term the sentence uses twice in the
  same form is reported once.

## Known gaps

- An expression whose parse in context differs from its parse in isolation is missed:
  `de cuando en cuando` is `fixed` under the adverb it modifies in a real sentence, but its own
  root when parsed alone.

# The terms a word is made of

`docs/instructions/` is the source of truth: where this contradicts the design, the design wins and
this document is what needs correcting. This one records what counts as an etymological component,
how it is detected, what the recursion costs, and what is deliberately left out.

Bru's call, **2026-09-20**, reversing the one recorded in
[Detecting a form-of](form-of-detection.md) six days earlier: *some etymologies are a sum of terms in
the same language, or an affixation, and when they are, those terms get cards too — recursively, and
including a surface analysis.* The older decision — that the Latin, the Arabic and the Quechua an
etymology walks back through get no cards — is untouched and is half of what the rule below is.

## Two kinds of dependency, and they are different kinds

A gloss now leans on its neighbours for two unrelated reasons:

| | names | what the reader is missing without it |
|---|---|---|
| a form-of | the word this one is an inflection **of** | `conocí` is `conocer` conjugated |
| a component | the words this one is made **of** | `descargar` is `des-` and `cargar` |

The first is [a form-of](form-of-detection.md) and is read from the definition. The second is read
from the etymology, and until now the etymology was prose on the card and nothing else: `descargar`
said *"Equivalent to des- +‎ cargar."* on a card whose reader had met neither word.

Both end up in the same place — `Gloss.depends_on`, a dependency always ordered before what needs it
— and `_dependencies` in `glosses.py` is the one function that asks all three questions of a sense
(the plain reading a figure stands on, the form-of's target, the etymology's components).

## What counts: a plus, and nothing else

Every term an etymology mentions is a link carrying the language section it points into:

```html
Equivalent to <i class="Latn mention" lang="es"><a href="/wiki/des-#Spanish">des-</a></i>
 +‎ <i class="Latn mention" lang="es"><a href="/wiki/cargar#Spanish">cargar</a></i>.
```

A component is a link in that paragraph such that **it points into the target language's own
section** and **stands in a run of links joined by `+`**. That is the whole test, and the plus is
what `{{affix}}`, `{{compound}}`, `{{univerbation}}`, `{{blend}}` and the `By surface analysis` line
all render. Three consequences worth stating:

- **A run of one is not a sum.** `Doublet of volear`, `Compare Portuguese voar`, `See sí` and the
  list of other apocopic forms under `gran` are same-language mentions too, and none of them says
  what the word is made of.
- **A run may be mixed.** `mamífero` is *"equivalent to Latin mamma +‎ -fero"*; only `-fero` is
  Spanish, and only `-fero` gets a card. The Latin half is prose on the card, as before.
- **A surface analysis is a sum like any other**, which is what the ask asked for: `venenoso` is
  `veneno +‎ -oso` however much Late Latin precedes it in the same sentence.

Two details the markup forced:

- **The link must carry a fragment.** The gloss inside a mention — `largo (“long”)` — links the
  *English* word, with no `#Language` on it. Reading every link had broken the run at that gloss and
  lost `largo` from `larguísimo`.
- **A split page is not the entry.** `a` is too long for one document, so `además` links
  `a/languages M to Z`. The `/languages …` tail is cut off; the card is for `a`.

Namespaced links are skipped for the same reason: `Appendix:Glossary#inherited` hangs off the word
*Inherited*, and `Reconstruction:Proto-Slavic/*` is not a page anyone can be taught.

## It is precise, and the looser rule is not

Measured over the warm page cache, per etymology block with prose — a block, not a page, because
`para` is a preposition under one etymology and a clipping of `paramilitar` under another:

| | blocks | link a same-language entry | **state a sum** | components |
|---|---|---|---|---|
| Spanish | 630 | 206 | **66** | 129 |
| Russian | 3,771 | 2,369 | **1,987** | 4,090 |
| Japanese | 1,355 | 588 | **108** | 228 |
| Chinese | 408 | 168 | **4** | 7 |
| German | 103 | 38 | **21** | 43 |
| French | 112 | 33 | **5** | 10 |

The second column is the rule decker does *not* use — every same-language link in the etymology — and
the gap between it and the third is the reason. In Spanish it is 206 against 66: the other 140 are
doublets (50 blocks say `Doublet of`), cognate lists (68 say `Cognate`), and `Compare` (92). A
learner of Spanish handed `volear` because `volar` is a doublet of it has been handed a word the text
never said and the word in front of them is not made of.

All 66 Spanish decompositions were read by hand. Every one is a genuine component:

```
     descargar -> des-, cargar          Equivalent to des- +‎ cargar.
      enamorar -> en-, amor, -ar        From en- + amor + -ar.
     venenoso  -> veneno, -oso          ... By surface analysis, veneno +‎ -oso.
 especialmente -> especial, -mente      ... equivalent to especial +‎ -mente.
        porque -> por, que              Univerbation of por (“for; due to”) + que (“what”).
    servilleta -> servir, -illa, -eta   ... Reinterpreted as a double diminutive servir +‎ -illa +‎ -eta.
      también  -> tan, bien             From tan (“so, as”) + bien (“well”).
```

Russian is the language this stage is *for*: more than half its etymology blocks state a sum, because
Russian derivation is affixal and Wiktionary writes it out — `снимать` is `с- +‎ -нимать`,
`переодеться` is `переодеть +‎ -ся`. Chinese is where it gives nothing, four blocks in 408: a Chinese
etymology is prose about the characters, not a sum of links.

## Recursion, and where it stops

A component is a word like any other, so it is glossed like any other: one sense of it, chosen
against the passage the *dependent* word was met in, and whatever that sense depends on in turn. A
chain therefore keeps going while Wiktionary keeps decomposing. Russian goes deepest of the measured
languages:

```
переодеться -> переодеть + -ся
               переодеть -> пере- + одеть
                            одеть -> о- + деть
```

What stops it:

- **The chain of titles being resolved is carried down**, so a pair of words whose etymologies name
  each other cannot loop. This is the same guard form-of resolution already used, now shared.
- **A page's own title is never its own component**, filtered in `Page.etymons_of`.
- **Affixes bottom out.** `-ся`, `des-` and `-mente` have etymologies of their own, and they are
  Proto-Slavic and Latin — no same-language sum, no further cards.
- **Everything is glossed once.** A page is fetched once per run and a gloss is one card per
  (form, sense) pair, so the second word built on `-ito` costs nothing.

## What it costs

`flamencos.txt`, 1,281 terms, Spanish, warm cache:

| | glosses |
|---|---|
| `--no-components` | 716 |
| with components | **786** |

**+70 cards, 9.8 %**, of which 59 are the component words themselves and the rest are what they in
turn pulled in — three more concept cards and a handful of form-of targets. The stage is one
disambiguation call per component page with more than one sense, and it fetches pages a text-only run
never asks for: when the rule was first measured, 63 of the 93 distinct Spanish components the
cache's own etymologies named had no page cached. That is the part that is slow on a cold cache and
free on a mirror.

*Measured with ollama unavailable, so disambiguation was degraded to "keep every sense" for the
words of the text.* A component is asked for on its own prompt with `single=True` and so is one card
either way; the 716 and the 786 are both inflated by the same outage, and the difference between them
is the stage.

Russian will cost more than this, in proportion to the table above — 1,987 sums in 3,771 blocks, and
the chains are three deep. That is not a reason to bound the recursion: the components *are* the
language's morphology, and a reader who has met `пере-`, `о-` and `деть` can read the next four verbs
built out of them. `--no-components` turns the stage off for a reader who disagrees.

## What is left out, and why

- **Ancestors in another language.** Bru's call of 2026-09-14 stands: the Latin, the Arabic and the
  Quechua stay as prose. A component is in the language being taught or it is not a card.
- **A single-term derivation.** `Deverbal from contar`, `Clipping of paramilitar`,
  `Past participle of descubrir` — 9, 2 and a handful of Spanish blocks. They name a real
  same-language relation, and they are not sums, so the rule above does not fire on them. Most are
  caught anyway where it matters, because the *definition* says the same thing and
  [the form-of detector](form-of-detection.md) reads it. Left alone rather than added by name: every
  marker added by hand is another list to maintain, and that is the mistake the form-of doc already
  records.
- **A second paragraph.** Only the paragraph the card shows is read, which is the first one with
  prose in it. 22 of 630 Spanish blocks have more, and a component named in a paragraph the card
  does not show would be a card with no visible reason to exist.
- **Culling.** The morphological rules stage is untouched. A component is a dependency, not an
  occurrence in the text, so it is never an instance of a rule and can never be culled away from
  under the word that needs it — the same reasoning as `_morphology`'s.

## Where it lives

- `pages.py`: `_etymology_paragraph` (the one paragraph, as markup), `_etymology` (its prose),
  `_etymons` (its sums), `_entry_title`. `Entry.etymons` carries them per block, `Page.etymons_of`
  answers per sense by identity the way `etymology_of` does.
- `glosses.py`: `_composed` reads them, `_dependency` glosses one word another leans on — shared with
  `_referenced` — and `_dependencies` is the three questions asked of every sense.
- `--no-components` turns the stage off; the run's tally says how many of the glosses it added.

# Detecting a form-of

`docs/instructions/` is the source of truth: where this contradicts the design, the design wins and
this document is what needs correcting. This one records what the detector is, how well it works,
what was measured about widening it, and what a better source would be.

Everything below is measured over the nine-source Spanish corpus of `deck-growth.md`: 3,092 word
glosses, built against the local mirror with `gemma4:latest`.

## What it is

Two regexes in `glosses.py`, and nothing else:

```python
_GRAMMAR = re.compile(r"\b(inflection|form|spelling|participle|gerund|degree|diminutive|…)\b", re.I)
_TARGET  = re.compile(r"\bof\s+([^\s,;:.()\[\]“”\"]+)")
```

`_targets` requires **both** — a grammar word from a hand-written list of twenty-four, and the
literal string `of` — and takes the token after the `of`. That one function decides three separate
things at once, which is worth saying plainly because they have different consequences when it is
wrong:

1. whether `_referenced` glosses the word this definition points at, so `conocer` gets a card
   because `conocí` names it;
2. whether the occurrence is put to the morphological rules stage at all;
3. and therefore whether the occurrence can ever be culled.

It is applied to `sense.definition` and to nothing else.

## It is precise

Of 3,092 word glosses, 1,283 fire it. Three pick a target that is not a word of the language:
`ir -> a`, `mil -> something`, and `señora -> address`, the last from *a title or form of address
for a woman*. **0.23 %.** Demanding a grammar word *and* `of` is what buys that, and it is worth
keeping in mind before either half is loosened.

## Widening it: the keywords are safe, the preposition is not

Measured by re-running the detector over the same 3,092 glosses.

| | newly firing | genuine | wrong |
|---|---|---|---|
| more keywords, still only `of` | 16 | 15 | 1 |
| more keywords **and** `of\|from\|to\|for` | 37 | 15 | **22 (59 %)** |

The second is a disaster and the reason is structural, not a matter of picking better words: every
Spanish verb is defined by an English infinitive, so `to X` matches the gloss itself.
`tomar -> take`, `hablar -> talk`, `doler -> hurt`, `haber -> exist`. A definition written in
English cannot be scanned for a Spanish word by looking for an English preposition.

Scored one at a time, only four markers earn a place, and only 19 glosses in the whole corpus want
them:

| marker | fires | targets |
|---|---|---|
| `equivalent` | 11 | amigo, bailarín, cocinero, compañero, cuñado, *distance* |
| `synonym` | 3 | pues, sala, uf |
| `ellipsis` | 1 | café |
| `contraction` | 1 | a |

The one false positive is `legua -> distance`, from *a traditional unit of **distance** equivalent
to…*; requiring the literal `equivalent of` removes it. `deverbal`, `comparative`, `collective`,
`alternative`, `obsolete`, `archaic` and the rest of the plausible list fire zero times here, so
carrying them would be speculation.

**So: add `female|male equivalent of`, `synonym of`, `ellipsis of`, `contraction of`; keep `of`.**
Sixteen new dependency glosses, no new false positives. Not yet done — it is a small change and the
next section may make it moot.

## Etymology targets get no cards

`carga`'s card says "Deverbal from cargar." and there is no card for `cargar`, because the detector
only ever sees `sense.definition`. Raised, and **decided against by Bru on 2026-09-14: an
etymology's targets are not glossed.** An etymology names Latin, Arabic and Quechua words that no
learner of Spanish should be handed a card for, and the relation it states is historical rather
than something the reader needs in order to read the sentence in front of them. The prose stays on
the card; the words in it stay uncarded.

## Wiktionary's own markup, which is what it now reads

Every form-of definition is marked in the rendered page, on the form's own
entry: `<span class="form-of-definition">` around the line and
`<span class="form-of-definition-link">` around the word it points at.
`glosses.references` now reads that first and falls back to the prose reader
only where there is none.

Measured per sense over the 3,092 word glosses before the change:

| | |
|---|---|
| both agree it is a form-of | **1,228** — of which 1,219 pick the same target |
| they pick a **different** target | **9** — and the markup is right in all nine |
| Wiktionary marks it, the prose reader misses it | **16** |
| the prose reader says yes, Wiktionary marks nothing | **55** |

The nine disagreements are one bug, and it is the reason to prefer the markup
even where both fire: **`_TARGET` takes the first token after "of", so every
multi-word lemma is truncated.** `bichitos de luz` pointed at `bichito`,
`frías gotas` at `gota`, `recién nacidas` at `recién`, `malas palabras` at
`mala`. Each of those glossed the wrong word as a dependency and handed the
wrong base word to the rules stage.

The sixteen are exactly the relations the word list does not know — `female
equivalent of`, `ellipsis of`, `reflexive of`, `feminine of cada uno`, `only
used in de reojo` — so the markup gets them without anyone maintaining a list,
and the widening measured above is moot.

The fifty-five are why the prose reader stays. They are genuine form-of lines
written by hand rather than through a template — `dative of yo`, `superlative
degree of mucho`, `apocopic form of suyo`, `masculine plural of el` — and
Wiktionary marks none of them. Neither reader is complete on its own.

## The headword line

The keyword list is decker guessing, from English prose, at something the page already states as
markup. Under every part of speech Wiktionary prints a headword line:

```html
<span class="headword-line">
  <strong class="Latn headword" lang="es">servilleta</strong>
  <span class="gender"><abbr title="feminine gender">f</abbr></span>
  (<i>plural</i> <b class="… form-of …"><a href="/wiki/servilletas#Spanish">servilletas</a></b>)
</span>
```

Gender carries a full `abbr title`; every inflected form is a link to its own page; and the class
`form-of` is Wiktionary's own word for the relation the regex is trying to recover. Over 400 cached
pages, 218 have a Spanish headword line, 91 carry a gender marker and 72 link inflected forms.
Verbs give their principal parts — `preguntar (first-person singular present pregunto,
first-person singular preterite pregunté, past participle …)` — and adjectives give all four
agreement forms.

Three reasons this matters more than a longer keyword list:

- **It cannot be wrong the way a regex is wrong.** There is no English prose to misread, so the
  `to take`/`to talk` failure above cannot happen.
- **It gives the forward direction.** The regex recovers *form -> lemma*, one form at a time, only
  when that form happens to be in the text. The headword line gives *lemma -> all its forms*, which
  is what a learner meeting `servilleta` actually wants to know and what the rules stage would need
  to state a rule from the paradigm rather than from one example.
- **It is where the code already is.** `_entries_in` walks to the part-of-speech heading and then
  to its `<ol>`; the headword line is the `<p>` in between.

### What was decided, and what was built

Bru's calls, 2026-09-14:

1. **The gender goes on the answers.** Not on a front: a recognition card that
   showed `f (plural servilletas)` above the word would be answering half of
   its own question.
2. **The paradigm goes on whichever word the page states it for**, and it
   **culls nothing** — an inflected form met in the text still gets its own
   card, and the rules stage is untouched.
3. **A paradigm form the text never uses gets no card.** The deck teaches the
   text; a paradigm is not in the text. So the headword line is something a
   card *shows*, never something that adds cards.

Built accordingly: `Entry.headword` holds the line minus the headword itself,
`Page.headword_of` answers per sense by identity the way `etymology_of` does,
`Gloss.headword` carries it, and `Side.headword` puts it on the answer of both
cards. Anki gains a `Headword` field on both note types, appended rather than
inserted so a collection already holding a decker note type gains a column
instead of renumbering the ones its notes already use.

An inflected form announces only itself, so its line comes back empty and its
card is unchanged. `carga`'s two nouns each say `f (plural cargas)`; its verb
form says nothing. `perro` says `m (plural perros, feminine perra, feminine
plural perras, diminutive perrillo…)`, `preguntar` gives its principal parts,
and `mate`'s six etymologies give `m` five times and `f` for the one that means
maths — gender per etymology, which only works because the section is cut by
etymology first.

**Still open:** the line's labels are English (`plural`, `feminine`), and the
translator does not see them, so a deck built with `--mother-lang` other than
`en` shows them untranslated.

# Concept identification: implementation choices

Written by an AI agent, not by hand. It records the choices taken while implementing concept
identification, which refine [the v1 design](../instructions/v1/design.md) without changing its
shape. The design documents remain the source of truth: where one of these contradicts them, the
design wins and the code is wrong.

The v1 section is three sentences: a concept is any text linked to `Appendix:Glossary#{concept}`,
its description comes from that glossary, and the card is titled `Concept: {concept}`. Most of
what follows is the consequence of taking that literally and finding where it needed a decision.

## What counts as a concept

- **The anchors are Wiktionary's own, and they are a gift.** Every piece of grammatical terminology
  in a rendered definition is a link to `Appendix:Glossary`, and the fragment is canonical and
  pre-disambiguated: `singular_number` rather than a bare `singular` that could be the adjective,
  `present_tense` rather than a `present` that could be the gift. This is what makes the stage
  possible without a lexicon of decker's own, and it also settles the naming problem the prose has
  — `first-person` and `first` are one anchor, `indefinite` and `strong` are one anchor. Across the
  1,744 pages in a warm cache, 27,090 links resolve to 295 distinct anchors and those to fewer
  concepts still.

- **Only the links inside a sense's own definition.** The design scopes concept identification to
  the terminology *inside a definition* — "dative plural of Hund" — and read literally, "any text
  that's linked" is wider than that: 14,528 of the 27,090 links in the cache sit outside any
  definition, in etymologies ("Inherited from", "doublet"), in pronunciation blocks ("Homophone:")
  and in section headings. `derived_terms` is one of the commonest anchors on the page and it is a
  heading, not a concept anyone should be taught. So a sense is credited with the anchors under the
  same subtree its own text is read from, which is the text that becomes the gloss's definition,
  and nothing else on the page contributes.

  The concrete cut this makes: `grito`'s plain sense *cry; shout; scream* yields nothing, and its
  form-of sense yields `first_person`, `singular_number`, `present_tense`, `indicative_mood`.

- **Sense labels are in, because they are in the definition.** `(ambitransitive) to shout, to
  scream` links `ambitransitive`, and `(colloquial)`, `(transitive)`, `(archaic)` link likewise.
  They are inside the text the card shows, and they are exactly what the design calls terminology
  that conveys a feature rather than a meaning, so they get cards. This is the largest source of
  concepts after the form-of tags, and it is worth knowing it was a choice: scoping to form-of
  definitions alone would have dropped them.

- **A header's terminology belongs to the lines under it.** Wiktionary writes `inflection of curar:`
  as a header with the readings beneath, and `_senses_of` already prefixes the header's text to each
  child. The anchors follow the same rule, so a child sense carries the header's terminology as well
  as its own.

## The glossary, and what a concept is called

- **One page, from Wikimedia, re-read only when it changes.** `Appendix:Glossary` is a single
  554 KB page holding the whole inventory, and it is read from `<edition>.wiktionary.org` whatever
  `--wiktionary-host` says. Two reasons: a mirror built from `pages-articles` has no `Appendix:`
  namespace, so pointing this at one would turn the stage off for exactly the runs a mirror is
  meant to serve; and the title is the same on every run and for every text, so asking for it says
  only that someone is using decker — which is not the vocabulary stream the mirror exists to keep
  off the network.

  It is a live wiki page that gains an entry now and then, so a cache with no way to notice would
  hold a stale copy for good, while re-fetching half a megabyte every run to find out would be
  worse. The revision id is asked for instead — a few hundred bytes — and the page itself only when
  that id has moved. A run that cannot reach Wikimedia keeps the copy it has; a glossary one
  revision old explains `dative case` exactly as well. Nothing is asked for at all when nothing is
  glossed, or under `--no-concepts`.

  Bru's call, 2026-09-11, over caching it like any other page.

- **Several anchors reach one entry, and one entry is one card.** The glossary is a definition list
  whose headings carry an invisible anchor per spelling: 1,005 anchors over 622 headings, resolving
  to 594 concepts with a description. `first_person`, `first-person` and `1st_person` are one
  entry; so are `singular`, `Singular`, `singular_number`, `sg`, `sg.` and `s`. Resolving the
  anchor to the entry before making a card is what keeps those from becoming three cards and six.

- **The name comes from the heading's text, not from the first anchor.** Both are orderings the
  page provides and they disagree. A heading lists its spellings fullest-first —
  `accusative case, acc.` — while the anchors on it are alphabetical, so taking the first anchor
  titled the accusative card **`Concept: acc.`** and the ablative one `Concept: abl.`. The first
  comma-separated item of the heading gives `accusative case`, `dative case`, `first person`,
  `singular`, `plural`, `present tense`, `indicative mood`. A handful of headings carry an
  interproject "English Wikipedia has an article on" box, which is skipped by its `noprint` class —
  without that, `transitive` was named `English Wikipedia has an article on:Transitivity
  (grammar)Wikipedia transitive verb`.

- **A few links point at entries that do not exist.** Nine of the 295 anchors in the cache have no
  heading on the glossary page — `intransitive_verb`, `clusivity`, `honorific` — and they are
  Wiktionary's own dangling links, not a parsing failure: the ids are absent from the page
  entirely. They are counted and named on stderr rather than guessed at, since the alternative is
  inventing a description for terminology decker cannot explain.

- **A missing glossary page is not three hundred broken links.** Since it is always read upstream,
  the one way to have none is Wikimedia being unreachable with nothing cached from an earlier run.
  The stage then stands down after saying so once, rather than reporting every anchor in the run as
  an entry that does not exist.

## How a concept reaches a card

- **A concept is a gloss, not a new kind of thing.** It has a title, a description, an identity and
  a place in the order, which is what a `Gloss` is, so it becomes one — and everything downstream
  follows without being told: the recognition/production pair, the dependency edges, the
  topological sort, the `.apkg` note, incrementality through `gloss_key`, and translation into the
  mother language. The alternative, a card kind of its own, would have meant touching all of that.

  **A concept gets the recognition card alone**, which is the one place it departs from "at least
  two cards" for every gloss. The production card asks for the term given the meaning, and a
  concept's term is the title decker itself gave the card, so the question would be about decker's
  naming rather than about the language being learned. Bru's call, 2026-09-11.

- **They are appended before the gloss that names them**, inside `_Builder.add`, so the concept
  always has the lower index and the design's ordering guarantee — a dependency before what depends
  on it — holds without any special case in shuffling. Verified on the built package: every
  `after N` in the shuffled order points backwards.

- **Identity is the pair every other gloss has**, the title and the text taught, so a concept met by
  twenty definitions is one card, and a concept a previous deck already teaches is left out exactly
  the way a known word is. `--previous` on a deck built with concepts skips them.

- **`Gloss.anchor` is new, and `Gloss.language` is doing something slightly different for a
  concept.** The credit link needs a fragment, and for a word that is its language section while
  for a concept it is the glossary anchor — `Appendix:Glossary#first_person`, not the top of a
  six-hundred-entry page. Rather than overload `language`, which the translator reads as the
  language a card teaches, concepts carry the anchor in a field of its own and keep the run's target
  language in `language`. `entry_url` takes whichever is set.

- **`--no-concepts` turns the stage off**, alongside `--no-disambiguate`, `--no-audio` and
  `--no-translate`. Not asked for by the design; added because the stage roughly doubles a small
  deck and because every other stage that costs something has a switch. Easy to remove.

## What this costs

Measured on 25 lines of real Spanish with disambiguation off, which is the worst case the stage
has: **699 word glosses and 54 concepts**, 7%. Thirty of the 54 come from form-of tags and 24 from
labels alone. With disambiguation on, the senses carrying those labels are mostly gone before this
stage sees them, so read 7% as a ceiling.

It is a ceiling in the stronger sense too. The glossary holds 594 entries and a text can only reach
the ones its words are described with, so the concept count saturates: `singular` is one card in a
deck however many inflected forms of however many verbs point at it, and a longer source adds word
cards without adding many more concepts. The cost is front-loaded, which is the point of the stage.

In cards: a concept is one card, not two, so 15 glosses of which 7 are concepts make 23 cards
rather than 30.

## Known gaps

- **A description is quoted whole, and some are long.** `present tense` runs to a paragraph with
  four examples in it; `indicative mood` is one line. The glossary is written to be read, not to be
  a card. Cutting to the first sentence is the obvious fix and was not made, because the design says
  the description comes from the glossary and because the sentence boundary is not reliable in text
  carrying `q.v.`, `e.g.` and `cf.`. Worth revisiting once these have been studied.

- **Concepts do not depend on each other.** Glossary descriptions reference other entries —
  `singular` says "usually contrasts with plural", `transitive verb` says "contrast intransitive
  verb" — and those links are exactly the shape this stage already resolves, so a concept could
  depend on the concepts its own description names. Not done: the design asks the *definition's*
  terminology to acquire cards, and recursing into the glossary is a further decision about how
  deep a deck should go before teaching the word the learner actually met.

- **A parenthetical rides along in one or two names.** `Concept: preterite (also spelled preterit)`
  is the glossary's own heading, taken as it is. It reads acceptably and was left alone rather than
  stripped, since stripping parentheses would need to know which ones are asides.

- **The stage is silent about which concepts a *mother* language already has.** The design dropped
  that constraint deliberately, so an English speaker gets a `Concept: plural` card. Noted here
  only so a reader of the code does not take its absence for an oversight.

# Definition fetching: implementation choices

Written by an AI agent, not by hand. It records the choices taken while implementing v1's
definition fetching, which refine [the v1 design](../instructions/v1-design.md) without changing its
shape. The design documents remain the source of truth: where one of these contradicts them, the
design wins and the code is wrong.

## Where the data comes from

- Two endpoints are read per title, because neither carries everything.

  The REST definition endpoint (`/api/rest_v1/page/definition/<title>`) keys its entries by language
  code, which is precisely the cut the pipeline needs — the title dump has no language dimension at
  all, so this is where a Spanish text stops being offered Chinese surnames. It also renders form-of
  definitions in full: `corrió` comes back as *third-person singular preterite indicative of
  correr*, which is the relationship the design asks the inflected gloss to explain, already
  written.

  Etymology, IPA and audio are not in that payload, so the rendered page (`action=parse`) is fetched
  too and read with regexes: `<span class="IPA ...">` for readings, the first `upload.wikimedia.org`
  media URL for audio, the first paragraph under an Etymology heading for etymology. The raw
  wikitext would have been the obvious source and is not usable: Spanish pronunciation sections
  carry `{{es-pr|...}}`, and the IPA only exists once that template has run.

- The language *name* needed to find the section in the HTML (`Spanish`) is taken from the REST
  payload's own `language` field, so no code-to-name table has to be kept anywhere.

- Both payloads are cached verbatim, one gzipped JSON per title under `pages-<edition>/`, so a page
  is fetched once however many terms land on it. Audio stays out of that file, as the design asks:
  the page keeps the URL and the sound file is written under `audio/` only when it is wanted.

- Wikimedia answered a burst of back-to-back requests with HTTP 429. Requests are now spaced half a
  second apart and a 429 or 503 is waited out, honouring `Retry-After` when the server sends one.

## Glosses

- A term is glossed from the first of its entries that actually has a section in the target
  language. `El` matched both the `El` page (a Semitic deity, no Spanish section) and `el`; the
  first is skipped and the article is what gets glossed.

- The lemma gets a gloss of its own only when its page is a *different* page from the one the
  inflected form was glossed from. `corrió` and `correr` are two pages, so there are two glosses and
  the first depends on the second. `Lo`, whose own page has no Spanish section, is glossed straight
  from `él`; a second gloss carrying the same definitions would be the repetition the design
  forbids.

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
  rather than two identical ones, while `España` keeps its capital. Where the entry is a *different*
  word — `enrulada` glossed from `enrulado`, for want of a page of its own — the text's form is kept,
  since the entry's spelling is not the term.

- The Markdown renderer gives `depends_on` a line of its own — **Depends on** [0. ser](#0-ser) —
  rather than a bare index trailing the fact line, where it was unreadable and unnavigable. The link
  targets the dependency's own heading, which the design's ordering guarantee already puts above.

- A gloss carries the sound file's URL as well as its cached path. The path is only set when the run
  downloaded audio; the URL is kept either way, so `--no-audio` still yields a document that links to
  the pronunciation. The Markdown renderer prints the URL and never the cache path, which would mean
  nothing to a reader.

## Sense disambiguation

- One ollama call per glossed occurrence, carrying the sentence with the occurrence bracketed, the
  form as it appears, and every sense of the page numbered and labelled with its part of speech; the
  model answers with the numbers it keeps, under a JSON schema. On `El perro corrió hacia la puerta` this cut `la` from
  eleven senses to the article alone and `correr` from thirteen to three.

- The default model is the design's `gemma4`. The host defaults to `$OLLAMA_HOST`, falling back to
  `http://localhost:11434`, ollama's own default. A server that lives elsewhere — a GPU box reached
  through a forwarded port, say — is named by the environment or by `--ollama-host`, so no one
  machine's network is written into the code. Ollama has no authentication, so it is never bound
  anywhere but a loopback or a tunnel.

- When ollama cannot be reached, or answers something unusable, the gloss keeps every sense and a
  warning is printed once. The design says disambiguation *must* happen, so this is a degraded run,
  not a supported mode; `--no-disambiguate` is the way to ask for it deliberately.

- The occurrence being judged is bracketed in the sentence the model is shown — `—Vaya, ⟨vaya⟩ a
  dormir.` — because a form can occur twice in one sentence as two different words. Unmarked, both
  calls carried the same sentence and the same surface, so the model could not answer differently
  even in principle: the interjection `Vaya` came back carrying the subjunctive sense while the
  actual subjunctive `vaya` had it dropped. Spans come from the tokens the term covers, so a
  multiword token (`del` = `de` + `el`) marks whole.

## Licensing

- Wiktionary's text is CC BY-SA 4.0, and a gloss quotes it whole — definitions, examples,
  etymologies. The Markdown document therefore ends with a line naming Wiktionary and the licence,
  which together with the per-gloss entry links is the attribution the licence asks for. Deck
  construction will need the same line somewhere a card carries it.

- Pronunciation files are licensed one by one on Commons, and decker keeps only the URL and the
  cached path — not the recording's author or licence. Nothing is redistributed while the file sits
  in `~/.cache/decker`, so v1 leaves this alone deliberately; a deck meant to be shared would have
  to collect the per-file credit from Commons first.

## Known gaps

- IPA is collected from the whole language section, so a page whose section covers several entries
  offers all of their readings: `el` comes back with `/el/ [el] /eɾ/ /e/ /a/`.

- Audio is the first media file in the language section, which can belong to a neighbouring entry —
  the `el` gloss is handed a recording of `él`.

- The REST payload lists usage notes among the definitions, so `la` arrives with sentences like
  *Used primarily in Spain* as if they were senses. Disambiguation drops them in practice, but a run
  with `--no-disambiguate` shows them.

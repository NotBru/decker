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

- A page whose definitions come back as Wiktionary's own failure text — a Lua timeout, rendered into
  the page under a normal 200 — is used for the run but never written to the cache. Cached, such a
  page is permanent: `de` and `o` had sat there long enough that every run asked the model to choose
  between fifteen copies of `The time allocated for running Lua modules has expired`. Not writing it
  costs one degraded run and lets the next one get the real page.

- A title too large for one page keeps its language sections on `<title>/languages A to L` and
  `<title>/languages M to Z`, and shows a footer of links in their place. `a` is the one such title
  the Barbapedro text reaches: the definition API returns English alone, and so does the raw
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

  A referenced word is glossed at one sense: the one its pointer relies on, asked for on its own
  prompt. `patita` depends on `pata` as "paw, foot, leg", not on all eight of its senses. Resolution
  recurses, and the chain of titles being resolved is carried down so a pair defined in terms of each
  other cannot loop.

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

- The default model is `gemma4:latest`, chosen by measurement rather than by what pulls cleanly:
  on the eight etymologies a German run left in English it answers all eight, where `gemma3:4b`
  echoes its English input back on three of them — an answer no schema and no fallback can tell
  from a good one. It pulls from the registry like any other tag; the cost is size — 9.6 GB against
  `gemma3:4b`'s 3.3 — so a host without the room degrades and says so, naming what it does hold. A model can also be
  named for a whole shell as `$DECKER_MODEL`, the way the host is named by `$OLLAMA_HOST`, because
  those two are exactly the pair that has to agree: a tunnelled GPU box and a laptop's own ollama
  hold different tags, so a host set in the environment and a model left to its default is the
  ordinary way a run asks for something that is not there. When it does, the warning names the tags
  the host *does* hold — a missing model otherwise comes back as its own name thrown back, which
  reads the same whether the tag is misspelled, the host is the wrong one, or it was never pulled.
  The host defaults to `$OLLAMA_HOST`, falling back to
  `http://localhost:11434`, ollama's own default. A server that lives elsewhere — a GPU box reached
  through a forwarded port, say — is named by the environment or by `--ollama-host`, so no one
  machine's network is written into the code. Ollama has no authentication, so it is never bound
  anywhere but a loopback or a tunnel.

- Every recording in the language section is fetched, not the first. A page can list several — `el`
  has one for Spain and one for Colombia — and which one a learner wants is not decker's to guess;
  the design says to fetch all that is available, and taking the first drops the rest silently.
  Wikimedia transcodes each recording into several formats, so the same clip arrives as `.ogg` and
  `.mp3`; those are one recording and not two, and a card holding both would just play it twice.
  They are grouped on everything but the last extension and the `.ogg` kept, being what the source
  is served as. `el` goes from one file to two recordings; `casi`, which has one, stays at one.

- A form-of header is put back onto the readings under it. Wiktionary writes a form with one
  reading inline — `third-person singular preterite indicative of correr` — and a form with several
  as a header naming the lemma with a nested list beneath it. The REST payload flattens the second
  shape into siblings: first a header sense holding every reading glued together, then each reading
  alone, without the lemma. Disambiguation then keeps one of the readings, correctly, and the card
  loses the only thing an inflected form has to say — what it is an inflection *of*. `auswanderte`
  reached a deck meaning no more than "first/third-person singular preterite".

  `_unflattened` prefixes each reading with the header and drops the header as a sense of its own,
  it being a container rather than a meaning: as a card it would claim the word is all of its
  readings at once. The test is containment, not wording — the header sense is literally its first
  clause followed by every child concatenated, so each child appears in it verbatim, and *every*
  later sense must be one, which keeps this off an entry that merely has a colon in its first
  definition. Across the cached pages it fired on 162 entries of 9,572 and left none of the shape
  behind. It is not a German problem: Spanish `cuenta`, Portuguese `tormenta`, Catalan `para` and
  Italian `tormenta` all have it, since what decides is how many readings a form has, not which
  language it is in. This is the same class as the usage-notes gap below — structure the REST
  flattening loses — but unlike that one it is detectable without guessing.

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

- IPA is collected from the whole language section. This was written up as a defect, citing `el`
  coming back with `/el/ [el] /eɾ/ /e/ /a/`; reading the page says otherwise. Four of those five are
  `el`'s own — the main reading, then Andalusian `/eɾ/` and rapid-speech `/e/`, both under `el`'s
  single Pronunciation heading. Only `/a/` comes from further down the page. Dialectal variants are
  the word's, and a learner is better off seeing them, so the readings stay as they are. What is
  genuinely wrong is small and structural: a page whose language section holds several etymologies
  pools their pronunciation blocks, and separating them means splitting the section by sub-heading.
  Left for v2.

- Audio was also written up as fetching a neighbouring entry's recording — the `el` gloss handed a
  recording of `él`. That is wrong too. The file Wiktionary lists under `el`'s own *Audio (Spain)*
  is merely *named* after `él` upstream, presumably by whoever uploaded it. Decker was reading the
  right section; a filename check would have rejected the file Wiktionary itself offers. Both claims
  came from reading the code and the filename rather than the page, which is the mistake worth
  remembering here.

- The REST payload lists usage notes among the definitions, so `la` arrives with sentences like
  *Used primarily in Spain* as if they were senses. **Accepted for v1.** The payload gives them no
  marker of any kind — they are plain `definition` strings with no examples, and so are plenty of
  real senses — so telling them apart means matching the HTML's *Usage notes* headings back against
  the REST text, which is fragile coupling for a case disambiguation already drops. It shows only
  under `--no-disambiguate`.

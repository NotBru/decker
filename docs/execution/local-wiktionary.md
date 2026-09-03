# A local Wiktionary

`docs/instructions/` is the source of truth: where this contradicts the design, the design wins and
this document is what needs correcting. Nothing here is wired into decker yet — it is a working
mirror and a record of what it took, not a change to the pipeline.

## Why a mirror at all

Three reasons, in ascending order of how much they matter.

- **Rate limits.** One deck is a few hundred requests; many users of one tool share one User-Agent,
  and `decker/*` is what Wikimedia would throttle or block. See `definition-fetching.md`.
- **Offline.** A run currently cannot happen without the network.
- **Privacy, which is the real one.** Every title decker fetches goes to Wikimedia in reading order,
  from one address, under a User-Agent naming the tool. A few hundred titles in order identify the
  source text; rare words are close to unique. This sits oddly beside the rest of the setup, where
  the model runs on hardware Bru owns precisely so the text never leaves it. The mirror closes the
  gap: the only observable act is "someone downloaded enwiktionary", which says nothing about which
  words were wanted.

Audio is the exception and stays a live fetch — see below.

## What exists

MediaWiki 1.43.9 (LTS) on MariaDB 10.11, holding the whole `enwiktionary-20260901`
`pages-articles` dump: **10,893,797 pages in 9.44 GB**, imported with `--no-updates`. Every
language renders — Latin, Cyrillic, Greek, Arabic, CJK, Hebrew, Devanagari, Hangul, Thai — and it
is browsable at `/wiki/<title>`.

It lives entirely outside this repository: `~/mw` (MediaWiki), `~/mwdata`, `~/dumps`, plus
`~/resume-wiktionary.sh` and `~/wiktionary-status.sh`. Nothing here is part of decker's package.

## Settings that had to be right, and why

Two of these cannot be fixed afterwards; they change what gets written during the import.

- **`$wgCapitalLinks = false`** — Wiktionary titles are case-sensitive. Set *after* an import, every
  template silently stops resolving: the import stored `Template:Slbor`, the wikitext asks for
  `Template:slbor`, and pages render with the template names showing as literal text. This cost a
  full re-import to discover.
- **`$wgCompressRevisions = true`** — gzip per revision. Wikitext compresses about fourfold, and it
  only affects rows written while it is on.
- **`$wgSitename = "Wiktionary"`** — the project namespace is derived from the sitename, so
  installing as "Wiktionary (local)" made `mw.title.new(x, 'Wiktionary')` fail with *unrecognized
  namespace*. This was most of the errors on CJK and Cyrillic entries.
- **`$wgExpensiveParserFunctionLimit = 2000`** — the default 100 is far below what an entry uses;
  the symptom is *too many expensive function calls*.
- **Scribunto `memoryLimit` at 2 GB** — the default cap kills the interpreter outright on
  Wiktionary's data modules. The symptom is *interpreter exited with status 1*, with no Lua
  traceback, which reads like a crash rather than a limit.
- **`$wgParserEnableLegacyHeadingDOM = false`** — emits the `<div class="mw-heading">` wrappers
  Wikimedia's parser produces. Without it the local HTML differs structurally from the API's.
- Extensions: **Scribunto** (`luastandalone`, `/usr/bin/lua5.1`), **ParserFunctions**,
  **TemplateStyles**, **Cite**. ParserFunctions is not in core, and without it `{{#if:}}` renders
  literally, which breaks nearly every template.

## Gotchas that cost time

- **`php-bz2` is required.** `importDump.php` reads `.bz2` directly, but without the extension it
  fails with a *no such file* error naming a file that plainly exists.
- **Importers cannot run in parallel.** Three at once died with
  `UltimateAuthority::__construct(): $actor must be UserIdentity, null given` — they race to create
  the same actor rows and the losers get null. Sequential import reaches ~1,500 pages/sec anyway;
  the database is the bottleneck, not the number of processes.
- **`flow-board` pages must be filtered out.** One chunk carried 2,133 StructuredDiscussions talk
  pages, and the importer throws `MWUnknownContentModelException` on the first one, ~105k pages in,
  losing the rest of the chunk. `~/dumps/strip-flow.py` drops them; they are discussion boards and
  contain no dictionary content.
- **Register PHP classes with `$wgAutoloadClasses`, never `require_once`.** At `LocalSettings.php`
  time no extension autoloader exists yet, so a class extending one of Scribunto's fatals and takes
  the whole wiki to HTTP 500.
- **Purge the parser cache after changing any of this** (`purgeParserCache.php --age 0`), or cached
  broken renders are served back and the fix looks like it did nothing.

## The `mw.wikibase` stub

`Module:labels` asks Wikidata for the display names of some dialect labels. Wikibase Client is the
extension that provides `mw.wikibase`, and it is a *reader* — it holds no data, so installing it
means either importing Wikidata's dumps, which dwarf Wiktionary's, or calling wikidata.org on
render, which is the exact exposure this mirror exists to remove.

`extensions/WikibaseStub/` registers a `mw.wikibase` that answers "no data" to everything, with a
metatable so unstubbed entry points return a nil-returning function rather than erroring. Nothing
is recovered — the labels are simply absent — but a page shows its definitions instead of an error
where its labels would be. Without it, `book` printed a Lua error in place of
`(Hong Kong Cantonese, colloquial)`; the definition itself was never affected.

## What the mirror cannot give

- **Audio URLs.** `File:` description pages are not in `pages-articles`, and the media itself is in
  no dump at all. A local render emits a red link where the API gives an `upload.wikimedia.org`
  URL. Either construct Commons URLs from the filename or keep fetching audio live — which leaves
  audio as the one residual privacy leak, far narrower than a full title stream but still
  vocabulary-shaped.
- **`Module:zh-glyph`** fails on `newBatch` for Chinese glyph-origin lines. Unrelated to Wikidata,
  unfixed, cosmetic.
- **Link tables, search and site statistics** are empty by choice: `--no-updates` skips the
  secondary updates, which would mean parsing all nine million pages and running Lua for each.
  Rendering is unaffected because pages parse on view, and red/blue link colouring is decided at
  parse time rather than from `pagelinks`. `refreshLinks.php` recovers them as its own long job.

## What is not done

Decker reads from the mirror. `--wiktionary-host http://172.17.0.2:8080` is the whole of it: the
mirror answers `/w/api.php` and `/wiki/<title>` at upstream's paths, and senses now come from the
rendered page rather than from `/api/rest_v1/page/definition/`, which no MediaWiki serves. A full
`define` run over one sentence produced 16 glosses with their dependencies, examples, etymologies
and readings intact, with nothing leaving the machine.

Nothing leaves it, audio included. The mirror's pages carry no media — `File:` pages are not in
`pages-articles` and the files are in no dump — so no recording is offered and none is fetched.
Bru's decision, 2026-09-03, is that this stays: **no audio with the mirror.** Commons URLs could be
constructed from filenames without the page's help, and that is exactly the narrow leak the mirror
exists to remove, so it is not done. A run against the mirror says once that it found no
recordings, since silence and absence look the same on a card.

# A local Wiktionary

`docs/instructions/` is the source of truth: where this contradicts the design, the design wins and
this document is what needs correcting. Decker now reads from the mirror when it is told to:
`--wiktionary-host` is the whole of the interface, and the rest of this is what stands behind it.

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

## How it was built

It runs on the dev container itself: PHP 8.3 with its built-in server, MariaDB 10.11, Lua 5.1.
Downloading took an hour, importing about six, nearly all of it unattended.

The pieces worth keeping are in the repository, under `tools/wiktionary/`: the config block, the
`WikibaseStub` extension, the router, the dump downloader, the import driver and the Flow filter.
`LocalSettings.php` is *not* there and should not be — the installer writes a database password, a
`$wgSecretKey` and a `$wgUpgradeKey` into it — and neither are the dumps, the database or this
machine's own start-up and status scripts. The wiki here loads the repository's block directly
(`require_once` at the foot of its `LocalSettings.php`), so what runs and what is documented cannot
drift apart. In order:

1. **Packages.** `mariadb-server`, `lua5.1`, `diff3`, and PHP with `bz2`, `mbstring`, `xml`,
   `intl`, `mysqli` and `curl`. `php-bz2` is the one worth checking twice — see the gotchas.

2. **MediaWiki and four extensions**, unpacked into `~/mw` from the tarballs kept in `~/mwsrc`:
   `mediawiki-1.43.9.tar.gz` for core, then `Scribunto-REL1_43`, `ParserFunctions`,
   `TemplateStyles` and `Cite` into `~/mw/extensions/`. The extension branch has to match the core
   release; only Scribunto's tarball says so in its name.

3. **The database, and the installer.** A first install went to SQLite and was abandoned before any
   import — its settings file is still beside the real one as `LocalSettings.sqlite.bak`. The real
   one went to MariaDB, through the CLI installer, which generated the first half of
   `LocalSettings.php` (the flags below are what that file implies; the invocation itself was not
   kept):

   ```
   php maintenance/install.php --dbtype=mysql --dbname=wiktionary \
       --dbuser=wikiuser --dbpass=wikipass \
       --server=http://localhost --scriptpath="" --pass=<admin password> \
       "Wiktionary (local)" admin
   ```

   That sitename was the mistake recorded below; the config block overrides it, which is why
   `$wgSitename` is assigned twice in the file.

4. **The config block, in place before a single page was imported.**
   `tools/wiktionary/config-block.php` goes below "End of automatically generated settings", by
   `require_once` or by pasting, with
   `tools/wiktionary/extensions/WikibaseStub/` copied into the wiki's own `extensions/`. Every
   setting in it is explained in the next section. Two of them — `$wgCapitalLinks` and
   `$wgCompressRevisions` — decide what the import writes to disk and are worthless afterwards, so
   this step cannot be deferred.

5. **The dump**, `tools/wiktionary/download-dump.sh`:

   ```
   EDITION=en DUMP_DATE=20260901 DUMP_DIR=~/dumps tools/wiktionary/download-dump.sh
   ```

   Nine `pages-articles` chunks, about 1.6 GB compressed, fetched one at a time with `curl -C -` so
   a dropped connection resumes rather than restarts, under a User-Agent naming this work. The
   chunk list is read from the dump's own `dumpstatus.json` rather than copied out of a directory
   listing by hand — that part was manual here and is not any more. Each finished chunk appends a
   `done <chunk>` line to `download.log`, which is what tells the importer a chunk is whole.

6. **The import**, `tools/wiktionary/import-driver.sh`: a loop over the chunk list running

   ```
   php maintenance/importDump.php --no-updates <chunk>
   ```

   one chunk at a time, touching `ok-<chunk>` on success and going round again for any that were
   still downloading. Sequential is not a simplification — see the gotchas — and it still reaches
   roughly 1,500 pages/sec, since the database is the limit. `--no-updates` is what makes that speed
   possible, at the price described under "What the mirror cannot give".

7. **The one chunk that would not import.** `p10500001p12000000` died ~105k pages in on a
   StructuredDiscussions page, and the retry loop then spent five and a half hours failing at the
   same place twenty times, re-importing those 105k pages on every pass.
   `tools/wiktionary/strip-flow.py` decompresses the chunk, drops the 2,133 pages whose content
   model this wiki has no handler for, and writes a filtered XML, which imported clean; its `ok-`
   marker was then touched by hand, since the driver only knows about the original file. That is
   why this machine's log ends on a FAILED line for a chunk that is fully imported. The vendored
   driver gives up after `MAX_FAILURES` attempts instead, names the chunk, and prints those three
   commands.

8. **Serving it.** PHP's own server, no Apache, with `tools/wiktionary/router.php`, which gives the
   mirror upstream's URL shape — `/wiki/<title>` for articles, `/w/api.php` and friends for entry
   points — so that a caller can change the origin and nothing else:

   ```
   cd ~/mw && PHP_CLI_SERVER_WORKERS=8 php -S 0.0.0.0:8080 -t ~/mw ~/mw/router.php
   ```

   Workers matter: rendering an entry runs Lua for a second or more, and a single-process server
   serializes the whole run behind it.

9. **Pointing decker at it.** `--wiktionary-host http://localhost:8080`, or
   `$DECKER_WIKTIONARY_HOST`. Nothing else changes.

### Running it again

The two scripts named here are this machine's, not the repository's: they assume a container with
`sudo`, `service mariadb`, and the wiki at `~/mw`, and none of that is worth carrying to anyone
else. The parts that are — the config, the router, the drivers, the filter — are under
`tools/wiktionary/`.

The container stops and takes the database and the web server with it. `~/resume-wiktionary.sh`
brings back whichever pieces are down and is a no-op for the ones that are not;
`~/wiktionary-status.sh` prints chunks downloaded, chunks imported, pages, database size and free
disk. As of 2026-09-03 a resume is all it takes: 10,893,797 pages, 9.44 GB, and a `define` run over
one sentence answers from `http://localhost:8080` with 11 glosses.

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
  URL. The two ways out — construct Commons URLs from the filename, or keep fetching audio live —
  both put a vocabulary-shaped stream back on the network, and both were refused: see the decision
  at the end of this document. A mirror's cards are silent, and a run says so.
- **`Module:zh-glyph`** fails on `newBatch` for Chinese glyph-origin lines. Unrelated to Wikidata,
  unfixed, cosmetic.
- **Link tables, search and site statistics** are empty by choice: `--no-updates` skips the
  secondary updates, which would mean parsing all nine million pages and running Lua for each.
  Rendering is unaffected because pages parse on view, and red/blue link colouring is decided at
  parse time rather than from `pagelinks`. `refreshLinks.php` recovers them as its own long job.

## What decker does with it

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

The cache follows from that. A page is cached by title alone, whichever source rendered it, because
the mirror and Wikimedia render the same entry from the same wikitext; the payload records which
answered, and that is read only to say what the page's silence about audio means. Keying the cache
by source instead — which is what this said until 2026-09-03 — meant a text read once against the
mirror and then extended against Wikimedia handed its whole vocabulary to Wikimedia, one title at a
time. That is the leak the mirror exists to close, so the cache is shared and the audio is what
gives way.

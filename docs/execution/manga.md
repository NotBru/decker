# Manga as a source

`docs/instructions/` is the source of truth: where this contradicts the design, the design wins and
this document is what needs correcting. The design omits source format normalization from v1 — "the
input is already text" — and [subtitles](subtitles.md) already bent that once, on Bru's instruction.
This is the same bend one step further, on Bru's instruction of 2026-09-18: read a `.mbz` archive,
take the sentences from the `lines` of each block's OCR, and let the rest of the pipeline do what it
does for a book.

## What a mokuro archive is

[mokuro](https://github.com/kha-white/mokuro) runs a text detector and `manga-ocr` over a volume's
pages and writes the result beside them. `0001.mbz.zip` is the zip it produces; `0001.mbz` is the
folder that zip unpacks to, of exactly the same shape, and decker reads both — `decker/manga.py` is
the whole of it, and `cli._one_source` reaches for it the way it reaches for a cue file.

```
0001.mbz.zip
├── 0001.png … 0071.png     the pages, which decker never opens
├── _ocr/0001.json … 0071.json
└── mokuro-metadata.json    series, volume, and the page order
```

Each `_ocr/<page>.json` holds `img_width`, `img_height`, and `blocks`:

| field | what it is | what decker does with it |
|---|---|---|
| `lines` | the columns the bubble's text is set in | joined back into one sentence |
| `box`, `lines_coords` | where on the page it was | nothing |
| `vertical` | whether the bubble is set top-to-bottom | nothing — the seam rule reads the script instead |
| `font_size`, `uuid` | the detector's own bookkeeping | nothing |

The volume measured throughout this document is Gokurakugai vol. 1: **71 pages, 461 blocks, 944
lines, 4,215 characters of OCR**. A volume is four and a half thousand characters of text inside 26
MB of PNG, which is why `_members` reads the JSON out of the archive and nothing else.

## A block is a sentence; its lines are not

`jq -r '.blocks[].lines[]'` is the shape of the data and not the shape of the text. A block is one
speech bubble — one thing somebody said — and its `lines` are that utterance cut into columns by how
wide the bubble happened to be. Five lines of one bubble on page 1:

```
もー / タオさん / いんなら / 出てください / よお
```

That is one sentence, and `いんなら` is not a word. Handing the parser the lines separately is the
same mistake as handing it a cue file's cues separately, so they are folded the same way: **the
block is the unit, and its lines are joined.** 275 of the volume's 461 blocks are more than one
line, median 2 and at most 6, so this is not an edge case — it is most of the text.

**The seam closes without a space when both sides are written in a script that does not space its
words.** Japanese is such a script and `タオさん` + `いんなら` joined with a space is two tokens where
the page had one; a bubble of English or Russian — a sign, a title page, a translator's note — is
not, and loses its word boundary if the seam closes up. `script_of` from
[teaching the script](teaching-the-script.md) already answers this per character, so the decision is
per seam rather than per `--target-lang`: a volume can hold both scripts and this one does.

## Reading order comes free

A comic is read right to left, top to bottom, in panels, and reconstructing that from the boxes
would mean segmenting the panels — which the OCR did not record. It does not have to be
reconstructed: **mokuro already emits the blocks in reading order.** Measured over the volume, of
the 398 consecutive block pairs, **391 (98 %) either start a new horizontal band or move leftward
within one** — which is band-wise right-to-left, which is how the page is read. Page 11's blocks come
in four bands, and the *x* of each runs right to left within it: 617→185, then
593→687→306→59, then 646→390→117→76, then 547→276→213→74 — the one step backwards in the second
band being the shape of the 2 % that the measurement counts against.

So the blocks are taken in the order they are given, and the pages in the order
`mokuro-metadata.json` lists them. The metadata is what supplies the page order rather than sorting
the names, because a volume whose pages are not zero-padded sorts `0010` before `0002`; without the
metadata the names are sorted anyway, which is right for what mokuro writes and is the best
available for anything else.

## Bubbles that are not words

Eighteen of the 461 blocks are punctuation and nothing else:

```
‼︎！  ⋯  ⋯⋯  ⋯．．？  ⋯⁉︎  ？？  ！  ？
```

A beat, a shock, a double take — drawn as punctuation, with nothing said. Term extraction handed one
has nothing to find, and the sentence it makes is noise in the count of what the deck covers. **A
block with no character in any script is dropped**, which is the test `script_of` already provides:
it answers `""` for everything that is not a writing system, so a block it answers `""` for
throughout has no word in it. That leaves **443 bubbles, 5,063 characters** for the pipeline.

What is *not* dropped is the sound effects. `午短短短知短う` is one — the OCR's reading of a
hand-drawn スパァン — and nothing available here tells it from speech: it is kanji in a box like any
other box. Those reach the pipeline, fail to find an entry, and meet `--unknowns`
([unknown words](unknown-words.md)), which is the stage that exists for exactly this and charges a
model call for each. A volume's worth is a handful of calls, not a stage of its own.

## The sentences are nine characters long

The median bubble is **8 characters** and the mean 9.4; the longest in the volume is 33:

> 壁にこんな落書きしたらおばちゃんに怒られてタオさんにボられるぞ‼︎

That is the whole context a disambiguation prompt gets for a word in it — `mark_occurrence` brackets
the occurrence inside its sentence and sends that. It is the same thinness measured on dialogue
subtitles, where the median sentence is six tokens, and the same conclusion applies: **it is not a
defect to fix, it is what the source is.** A comic's line is short because a bubble is small. The
one thing it changes is that sense disambiguation on a manga is working nearer the edge of what the
sentence can tell it than it is on prose, and a deck built from one should be read with that in
mind.

## What the first volume turned up, which is not about manga

The deck built on 2026-09-18 — 443 bubbles, 2,284 terms, **1,507 glosses and 2,977 cards** with
`--teach-script` on, 32 concept cards and 487 symbols in a pair each — is a sound deck, and
building it surfaced one thing worth naming here because a manga is a good way to hit it: **116 of its terms were reported `no Japanese
section` and 89 of them have one**, the English Wiktionary writing an alternative spelling as a soft
redirect. That is 飲む, 分かる, ください, ダメ. It was a definition-fetching limitation, it cost a
Japanese deck from any source, and it was fixed on 2026-09-18 — the write-up is under
[Japanese in the language survey](language-survey.md) and
[definition fetching](definition-fetching.md). Manga is where it showed worst, a comic being written
in whichever spelling the letterer preferred.

No rules cards, either, which is the survey's other Japanese finding and is expected: Japanese
entries carry no glossary-linked form-of lines, so there is no feature bundle for the rules stage to
work from.

## Naming

An archive is named after its volume number and nothing else — `0001.mbz.zip` — so the deck would be
`0001` in an Anki collection that will hold next month's `0001` too. Two things follow:

- **The filename drops both extensions.** `Path.stem` takes one off and leaves `0001.mbz`, so the
  deck would be written to `0001.mbz.apkg`; `cli._stem` takes the pair off, since the double
  extension is the archive's own convention.
- **The deck's title comes from the metadata**, which knows the series: `Gokurakugai 0001`. The
  *filename* still comes from the file, that being where the user said to put it, and `--name`
  overrides either.

## What it does not do

- **No pictures.** A card that showed the panel a word was said in would be a better card and is a
  licensing question the deck-building document is already explicit about: no sentence of the source
  reaches a card, and no page of it does either. The PNGs are never read.
- **No furigana.** mokuro's OCR returns the text as printed and does not separate ruby from base, so
  a reading printed beside a kanji arrives inline if it arrives at all. What a card says about a
  reading comes from Wiktionary, as it does for every other source.
- **No speaker, no panel, no page on the card.** The page a bubble was on is known and dropped,
  exactly as a cue's timing is dropped. The analogue of [the timeline](timeline.md) — how far into
  the deck a reader must be to read page 40 — is a real thing to build and is not built.
- **No sniffing standard input.** A cue file can arrive on stdin and be recognized; an archive is a
  zip, decker reads stdin as text, and `-` is never a manga.
- **No `.mokuro`.** mokuro's older single-file output — one JSON of every page beside a folder of
  images — is a different shape and is not read. `.mbz`, its zip, and any folder holding an `_ocr/`
  are.

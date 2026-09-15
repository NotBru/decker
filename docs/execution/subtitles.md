# Subtitles as a source

`docs/instructions/` is the source of truth: where this contradicts the design, the design wins and
this document is what needs correcting. The design omits source format normalization from v1 — "the
input is already text" — and a subtitle file is the first input that is text only after four fifths
of it is thrown away. Bru's instruction, 2026-09-15: read `.srt` and `.vtt`, fold the cues into
running text, and let the sentence splitter do the rest. That is what this does, with one thing
added that the measurement forced.

## What a cue file is, once the timing is gone

The same prose every other source holds, cut into two-second pieces by how fast a viewer reads. A
sentence runs across cue boundaries as often as not, so the pieces are folded back together: cue
indices, timing lines and the WebVTT header go, and what is left is joined. `decker/subtitles.py` is
the whole of it, and `cli._source_text` reaches for it **by extension** — `.srt` and `.vtt`. Standard
input has no extension, so it is sniffed instead: a timing line is unmistakable, and sniffing also
catches a cue file saved under the wrong name.

Three things a cue file has that a book does not.

- **Rolling repeats.** YouTube's automatic captions scroll: cue *n* ends with the line cue *n+1*
  opens with, so the viewer sees a stable two-line block. Folded naively every line lands twice and
  the deck teaches every word twice. A line equal to the one kept before it is dropped, which unrolls
  exactly this and nothing else.
- **Markup that is not words.** Inline karaoke timestamps `<00:00:04.320>` and the `<c>` spans around
  them, `<i>`/`<b>`, ASS overrides `{\an8}`, the dash in front of a second speaker's line, and the
  bracketed cues — `[Music]`, `[APPLAUSE]` — that describe the soundtrack rather than say anything in
  the language being learned.
- **No sentences at all, when a machine wrote them.** This is the one that needed more than folding.

## Machine captions have no punctuation, and Stanza needs some

Measured on a synthetic but faithful YouTube caption file — three minutes of speech, no punctuation,
no capitals, rolling repeats:

| | characters | sentences | longest | parse |
|---|---|---|---|---|
| folded with spaces | 4,566 | **1** | 866 words | 36.9 s |
| folded with the timing | 4,586 | **21** | 52 words | 3.7 s |

One sentence of 866 words is not a parse problem only. The sentence is the context decker puts in
*every* disambiguation prompt — `mark_occurrence` brackets the occurrence inside it — so an
unsplittable caption file would put four and a half thousand characters in front of the model once
per card, for a question about one word. The length of a sentence is a cost paid per card.

So the file decides:

- **Punctuated subtitles are folded whole** and the splitter does its job, which is what it does for
  every other source. A tenth of the cues ending in something terminal is enough to count as
  punctuated (`PUNCTUATED = 0.1`) — subtitles written by a person are near 1.0 and machine captions
  are 0.0, so the threshold only has to tell those apart.
- **Machine captions get their boundaries from the timing**, which is the one piece of sentence
  structure that survives transcription: speech pauses at a full stop. A gap of `PAUSE = 0.8`
  seconds between cues is a break. And because cues in continuous speech often butt up against each
  other exactly — no gap to find — a run is broken at `MAX_WORDS = 40` whatever the timing says, so
  nothing unbounded can reach the parser or a prompt.

A break is written as a blank line, because that is what Stanza splits on: measured, a bare newline
inside a clause changes nothing (1 sentence) and a blank line makes two.

The sentences that come out of an unpunctuated file are fragments — they begin and end where the
speaker breathed, not where a clause does. Term extraction does not mind, since a term is a subtree
of one sentence either way; what suffers is the disambiguation context, which is now 40 words of
speech instead of a written sentence. That is the trade, and it is the better half of it.

## What it does not do

- **No speaker attribution.** `<v Speaker>` and the leading dash are stripped, not recorded. A deck
  teaches words, and which character said one is not on a card.
- **No timing on the card.** The cue times are read, used for the boundaries above, and dropped. A
  card that could play its line is a different feature and a licensing question — see
  [deck building](deck-building.md), which is explicit that no sentence of the source reaches a card.
- **No translation pairing.** A `.srt` in the target language and one in the mother language are two
  files and decker reads one. Aligning them would make a translation pair per line, which is a deck
  of a different shape than the design's.
- **Nothing is de-duplicated across cues but the rolling repeat.** A chorus repeated twenty times in
  a song is twenty cues, and the deck teaches those words once because a gloss is identified by form
  and sense, not by occurrence.

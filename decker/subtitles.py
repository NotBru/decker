"""Subtitle files as running text: what a `.srt` or `.vtt` is once timing is gone.

The design leaves source format normalization out of v1 -- "the input is already
text" -- and a subtitle file is the first input that is text only after most of
it is thrown away. What a cue file holds is the same prose every other source
holds, cut into two-second pieces by how fast a viewer reads, with an index, a
timestamp and sometimes karaoke markup around each piece. A sentence runs across
cue boundaries as often as not, so the pieces are folded back together and the
sentence splitter is left to find the sentences, which is what it does for every
other source.

Three things a cue file has that a book does not:

* **Rolling repeats.** YouTube's automatic captions scroll: each cue repeats the
  tail of the one before so the viewer sees a stable two-line block. Folded
  naively, every line lands twice and the deck teaches every word twice.
* **Markup that is not words.** Inline karaoke timestamps `<00:00:04.320>` and
  the `<c>` spans around them, `<i>`/`<b>`, ASS overrides `{\\an8}`, and the
  bracketed sound cues `[Music]`, `[APPLAUSE]` that describe the soundtrack
  rather than say anything in the language.
* **No sentences at all, when a machine wrote them.** Measured on a synthetic
  but faithful YouTube caption file -- three minutes of speech, no punctuation,
  no capitals -- folding the cues gives Stanza 4,566 characters with nothing to
  split on, and it returns *one sentence of 866 words*. That sentence is then
  the context in every disambiguation prompt the run makes. Real subtitles are
  punctuated and have no such problem, so the file decides: see :func:`text_of`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

#: What decker reads as cues rather than as prose, by extension. SubRip and
#: WebVTT differ in their timestamp punctuation and in the header, and in
#: nothing else that matters once the timing is dropped.
SUFFIXES = (".srt", ".vtt")

#: A cue's timing line, in either dialect -- `00:00:01,000 --> 00:00:03,120`,
#: `00:01.000 --> 00:03.120` -- with WebVTT's trailing cue settings if it has
#: them. The hours are optional in WebVTT and always present in SubRip.
_TIMING = re.compile(
    r"^\s*(?:(\d{1,3}):)?(\d{1,2}):(\d{2})[.,](\d{1,3})\s*-->"
    r"\s*(?:(\d{1,3}):)?(\d{1,2}):(\d{2})[.,](\d{1,3})"
)
#: A SubRip cue index: a line that is nothing but a number.
_INDEX = re.compile(r"^\s*\d+\s*$")
#: WebVTT's header and the keywords that introduce metadata, not words.
_HEADER = re.compile(r"^\s*(?:WEBVTT|NOTE|STYLE|REGION|Kind:|Language:)")
#: Karaoke timestamps and the tags around them, ASS overrides, and the
#: bracketed or parenthesised cues a transcript writes for a deaf viewer.
_MARKUP = re.compile(
    r"<\d{1,3}:\d{2}:\d{2}[.,]\d{1,3}>"
    r"|</?[a-zA-Z][^>]*>"
    r"|\{\\[^}]*\}"
    r"|\[[^\]]{0,40}\]"
    r"|\((?:music|applause|laughter|laughs|sighs)[^)]*\)",
    re.IGNORECASE,
)
#: What a subtitle puts in front of a line to say the speaker changed: a dash
#: in hand-written subtitles, and `>>` in everything derived from YouTube's
#: captions -- 2,753 of them in one series' file, which would otherwise be
#: 2,753 tokens of prose that nobody said.
_SPEAKER_MARK = re.compile(r"^\s*(?:>>+|[-–—])\s*")
#: What a sentence ends with, in the scripts decker has been run over.
_TERMINAL = ".!?。！？…"

#: A file is taken to be punctuated when this share of its cues ends in
#: something terminal. Subtitles written by a person are near 1.0 and machine
#: captions are 0.0, so the threshold only has to tell those apart; a tenth is
#: low enough that a transcript of mostly dialogue still counts as punctuated.
PUNCTUATED = 0.1
#: A silence this long between cues is taken for a sentence boundary, when the
#: file offers no punctuation to find one with. Speech pauses at a full stop;
#: this is the evidence the timing carries and the words do not.
PAUSE = 0.8
#: And a run of unpunctuated cues is broken here whatever the timing says.
#: Nothing unbounded may reach the parser or a prompt: the sentence is the
#: context every disambiguation call carries, so its length is a cost paid
#: once per card. Forty words is a long spoken sentence.
MAX_WORDS = 40


@dataclass(frozen=True)
class Cue:
    """One cue: when it is shown, and the words on it."""

    start: float
    end: float
    text: str


def text_of(raw: str) -> str:
    """The words of a cue file, in order, as one text.

    Punctuated subtitles are folded whole and the sentence splitter does its
    job. Machine captions have no sentences in them, so the boundaries come
    from the one thing that survives the transcription -- the timing: a pause
    of :data:`PAUSE` seconds is a break, and a run of :data:`MAX_WORDS` words
    is a break whether the speaker paused or not. A blank line is how that is
    said to Stanza, which splits on one and not on a bare newline.
    """
    cues = _cues(raw)
    if not cues:
        return ""
    ending = sum(1 for cue in cues if cue.text.rstrip().endswith(tuple(_TERMINAL)))
    if ending >= PUNCTUATED * len(cues):
        return " ".join(cue.text for cue in cues)

    out: list[str] = []
    words = 0
    for position, cue in enumerate(cues):
        if out:
            paused = cue.start - cues[position - 1].end >= PAUSE
            out.append("\n\n" if paused or words >= MAX_WORDS else " ")
            if paused or words >= MAX_WORDS:
                words = 0
        out.append(cue.text)
        words += len(cue.text.split())
    return "".join(out)


def looks_like(raw: str) -> bool:
    """Whether a text read from somewhere unnamed -- stdin -- is a cue file.

    The timing line is the tell: nothing in prose looks like `-->` after a
    clock. The first forty lines are enough, a cue file's first cue being at
    the top of it.
    """
    head = raw.splitlines()[:40]
    return any(_TIMING.search(line) for line in head) or bool(
        head and _HEADER.match(head[0])
    )


def _cues(raw: str) -> list[Cue]:
    """The file's cues, cleaned of markup, with the rolling repeats unrolled.

    A line equal to the one kept before it is dropped, which is what unrolls a
    scrolling caption: cue *n* ends with the line cue *n+1* opens with, and the
    two are one line said once.
    """
    cues: list[Cue] = []
    timing: tuple[float, float] | None = None
    lines: list[str] = []
    last = ""

    def flush() -> None:
        nonlocal lines
        if timing is not None and lines:
            cues.append(Cue(timing[0], timing[1], " ".join(lines)))
        lines = []

    for line in raw.splitlines():
        clock = _TIMING.match(line)
        if clock:
            flush()
            timing = (_seconds(clock, 0), _seconds(clock, 4))
            continue
        line = _MARKUP.sub(" ", line)
        line = _SPEAKER_MARK.sub("", line).strip()
        line = re.sub(r"\s+", " ", line)
        if not line or _INDEX.match(line) or _HEADER.match(line):
            continue
        if line == last:
            continue
        last = line
        lines.append(line)
    flush()
    return cues


def _seconds(clock: re.Match, offset: int) -> float:
    """One side of a timing line, as seconds."""
    hours, minutes, seconds, fraction = (clock.group(offset + n) for n in (1, 2, 3, 4))
    return (
        int(hours or 0) * 3600
        + int(minutes) * 60
        + int(seconds)
        + int(fraction) / 10 ** len(fraction)
    )

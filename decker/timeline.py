"""How far into a deck a viewer has to be to follow a subtitle file.

A deck built from subtitles is studied in one order and watched in another.
The deck's order is the text's, shuffled inside a week (`shuffling.py`); the
file's order is the clock. This stage puts the two side by side: for every
timestamp, the words said up to it, and how far into the deck the cards that
teach them sit.

The question it answers is "when can I watch up to here", and the answer is a
position in the deck -- *you must have studied this many cards* -- divided by
the rate the reader introduces new cards. That is the honest unit: decker
knows the order of the cards and nothing at all about how fast their owner
studies, so the rate is a flag with Anki's own default and the days are that
division, not a prediction.

Three things it needs, and two it cannot have:

* **The cues' clock**, which `subtitles.timed` keeps: the same fold the
  pipeline reads, with each cue's offset into it.
* **Where each gloss was first met**, which `Gloss.first_sentence` records and
  the sentence's own offset turns into a time.
* **Where each card sits in the deck**, which `anki.placed` reads back out of
  the package, so this reports the deck the reader has rather than the deck a
  fresh run would build. Decks are shuffled without a seed by default: a
  rebuild is a different order, and only the file can say which one.

What it cannot have is a claim that the reader *understands* the passage. A
card is a word met once, not a word known, and the deck teaches the words of a
text and not its grammar. And it cannot honestly headline the furthest card of
a stretch, which is what "understand all of it" would mean: the last few
percent of any stretch are scattered the length of the deck, for a reason that
is the rules stage's and not the passage's --
`docs/execution/timeline.md` has the measurement. So the figure is a share,
:data:`COVER` by default, and the furthest card is carried beside it.
"""

from __future__ import annotations

import bisect
import math
from dataclasses import dataclass

from decker import anki, subtitles
from decker.cards import RECOGNITION
from decker.console import log
from decker.glosses import Gloss
from decker.pipeline import SentenceTerms

#: Anki's own default for how many new cards a day a deck introduces, and so
#: the default for turning a position in the deck into a date.
RATE = 20
#: How much of the file one row covers, in seconds. Five minutes is nine rows
#: for an episode and eighty for a series watched end to end, which is a table
#: a person reads; a row per cue would be seven thousand of them.
EVERY = 300
#: What share of a stretch's words the headline figure is for. Measured
#: rather than chosen: a deck teaches a handful of its words from some late
#: occurrence rather than their first -- the rules stage culls the early ones
#: -- so the furthest card of even the first ten minutes is most of the way
#: through the deck and says more about the culling than about the passage.
#: Ninety-five percent is also where the reading-comprehension literature puts
#: the threshold for following a text unaided, which is the nearest thing to a
#: principled number available here.
COVER = 0.95


@dataclass(frozen=True)
class Row:
    """One timestamp, and what following the file up to it costs."""

    #: Seconds into the file, at the end of the stretch this row covers.
    at: float
    #: Cues that have started by then.
    cues: int
    #: Distinct glosses those cues need: the words said so far, sense by
    #: sense, plus the concepts and rules their definitions rest on.
    glosses: int
    #: How many of those the deck does not teach at all -- see :func:`gaps`.
    #: They count in :attr:`glosses` and can never be reached, so a stretch
    #: with more of them than the share leaves over has no :attr:`cards`.
    untaught: int
    #: Study this far into the deck, in its own order, and the share asked
    #: for has been taught. ``None`` when the untaught put it out of reach.
    cards: int | None
    #: Those cards at the reader's rate, in days.
    days: float | None
    #: The whole of it: the position of the furthest card among the words
    #: said so far that the deck teaches at all.
    furthest: int
    #: That, in days.
    furthest_days: float

    @property
    def taught(self) -> int:
        return self.glosses - self.untaught


def measure(
    glosses: list[Gloss],
    sentences: list[SentenceTerms],
    cues: list[subtitles.Placed],
    deck: list[anki.Placed],
    *,
    every: int = EVERY,
    rate: int = RATE,
    cover: float = COVER,
) -> list[Row]:
    """A row per ``every`` seconds of the file, to its last cue."""
    clock = _times(sentences, cues)
    positions = _positions(deck)
    starts = [placed.cue.start for placed in cues]
    end = max((placed.cue.end for placed in cues), default=0.0)

    #: Glosses in the order the *viewer* meets them, which is not quite the
    #: order they were made in: the parser's sentences are not the cues, and
    #: one sentence of a subtitle file runs across several of them.
    met = sorted(
        (
            (
                clock[gloss.first_sentence]
                if 0 <= gloss.first_sentence < len(clock)
                else 0.0,
                positions.get(gloss.key),
            )
            for gloss in glosses
        ),
        key=lambda pair: pair[0],
    )

    rows: list[Row] = []
    #: The positions met so far, kept sorted: every row asks the same question
    #: of a longer prefix -- how far in does this share of them reach.
    reached: list[int] = []
    untaught = 0
    position = 0
    for cutoff in _cutoffs(end, every):
        while position < len(met) and met[position][0] <= cutoff:
            where = met[position][1]
            if where is None:
                untaught += 1
            else:
                bisect.insort(reached, where)
            position += 1
        needed = _share(reached, untaught, cover)
        furthest = reached[-1] if reached else 0
        rows.append(
            Row(
                at=cutoff,
                cues=bisect.bisect_right(starts, cutoff),
                glosses=len(reached) + untaught,
                untaught=untaught,
                cards=needed,
                days=None if needed is None else _days(needed, rate),
                furthest=furthest,
                furthest_days=_days(furthest, rate),
            )
        )
    return rows


def gaps(glosses: list[Gloss], deck: list[anki.Placed]) -> list[Gloss]:
    """The glosses of the file that no card in the deck teaches.

    Four ways one gets here, and only the last is the deck being wrong:

    * the rules stage culled every occurrence of that form, the reader having
      been shown the rule behind it and the base word's card;
    * a previously built deck taught it and ``--previous`` left it out;
    * the deck was built with a stage this run has on -- concepts, rules,
      ``--teach-script`` -- or the other way about;
    * the deck predates the word, having been built from an earlier cut of
      the file.

    So a gap is a card the reader will not be shown, not necessarily a word
    they cannot follow, and it is reported rather than folded into the answer.
    """
    positions = _positions(deck)
    return [gloss for gloss in glosses if gloss.key not in positions]


def report(rows: list[Row], glosses: list[Gloss], deck: list[anki.Placed]) -> None:
    """What the run says about the measurement it has just made."""
    missing = len(gaps(glosses, deck))
    studied = sum(1 for card in deck if card.studied)
    total = sum(1 for card in deck if not card.studied)
    log(
        f"[decker] {len(rows)} rows over {len(glosses)} glosses; "
        f"{total} cards to study"
        + (f", {studied} already studied" if studied else ""),
        kind="head",
    )
    if missing:
        log(
            f"[decker] {missing} of the file's glosses are in no card of this "
            "deck: culled by a rule, left out as already taught, or built "
            "with a different set of stages",
            kind="warn",
        )


def _share(reached: list[int], untaught: int, cover: float) -> int | None:
    """How far into the deck ``cover`` of the words met so far are taught by.

    The untaught are counted and never reached, which is what makes a share
    unreachable rather than merely expensive: a stretch of which a twentieth
    is in no card of this deck has no position that teaches nineteen
    twentieths of it, and saying so is the point.
    """
    total = len(reached) + untaught
    if not total:
        return 0
    wanted = math.ceil(cover * total)
    if wanted > len(reached):
        return None
    return reached[wanted - 1]


def _days(cards: int, rate: int) -> float:
    """Cards as days, at a rate of new cards a day."""
    return cards / rate if rate else 0.0


def _cutoffs(end: float, every: int) -> list[float]:
    """The timestamps rows are written at: every ``every``, then the end.

    The last row is the end of the last cue rather than the next multiple, so
    the table's final line is the file's own length and says what the whole
    of it costs.
    """
    every = max(every, 1)
    marks = [float(mark) for mark in range(every, int(end) + 1, every)]
    if not marks or marks[-1] < end:
        marks.append(end)
    return marks


def _times(sentences: list[SentenceTerms], cues: list[subtitles.Placed]) -> list[float]:
    """When each sentence was said: the start of the cue it opens in.

    A sentence crossing a cue boundary is timed by where it starts, which is
    when the viewer first hears its words. A sentence the parser gave no
    offset for, and anything before the first cue, is timed at zero rather
    than dropped: it is material the file carries, and the viewer meets it
    whenever they start watching.
    """
    offsets = [placed.offset for placed in cues]
    times = []
    for sentence in sentences:
        if sentence.start < 0 or not offsets:
            times.append(0.0)
            continue
        found = bisect.bisect_right(offsets, sentence.start) - 1
        times.append(cues[max(found, 0)].cue.start)
    return times


def _positions(deck: list[anki.Placed]) -> dict[str, int]:
    """Per gloss, how far into the deck it has been taught by.

    The recognition card, which is the one that teaches a word its meaning:
    producing the word from its meaning is a further skill and not one that
    following a subtitle asks for. A gloss whose recognition card has already
    been studied costs nothing further and answers zero.
    """
    positions: dict[str, int] = {}
    for card in deck:
        if not card.key or card.kind != RECOGNITION:
            continue
        positions[card.key] = max(positions.get(card.key, 0), card.position)
    return positions


def clock(seconds: float) -> str:
    """A timestamp as a subtitle file writes one, to the second."""
    whole = int(seconds)
    return f"{whole // 3600:02d}:{whole // 60 % 60:02d}:{whole % 60:02d}"

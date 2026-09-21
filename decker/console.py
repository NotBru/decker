"""One place decker speaks from: levels, colour, a bar, and a screen.

Until now every stage printed to stderr directly, which was fine when a run was
a few hundred lines and is not when it is a series: the lines that matter --
what was skipped, what could not be fetched -- scroll past between thousands
that do not, and nothing says how far along a run is. So:

* **A level per line.** `--quiet` leaves errors, the default leaves the shape of
  the run, `-v` names every word as it is looked up, `-vv` adds what was asked
  of the model. A long run is watchable at `-v` and readable afterwards at the
  default.
* **A colour per level**, so the eye finds a warning in a wall of detail.
* **A bar on the bottom line**, and log lines that scroll above it. The bar is
  drawn last on every write, so it stays where it is while the log moves up.
* **A screen**, when there is a terminal to draw one on: the same log down the
  left, a running tally of what the deck is made of down the right, and the bar
  along the bottom. `decker/screen.py` draws it; this file remains the only
  thing the stages talk to, and it keeps the counts the screen reads.

None of it happens when stderr is not a terminal: a redirected run writes plain
lines in order, which is what a file or a pipe wants, and what every measurement
in `docs/execution/` was taken from.
"""

from __future__ import annotations

import os
import shutil
import signal
import sys
import threading
import time
from collections import Counter, deque
from contextlib import contextmanager
from dataclasses import dataclass, field

#: What a line has to be worth to be printed. `QUIET` keeps what a run cannot
#: continue past; `NORMAL` keeps the shape of it, which is what every example in
#: the documentation shows; `VERBOSE` names each word; `DETAIL` adds the model.
QUIET, NORMAL, VERBOSE, DETAIL = 0, 1, 2, 3

#: Kind of line, and the colour it gets. Errors and warnings are what a reader
#: is scanning for, so they are the two that carry colour on their own; a
#: heading is bright because it is the skeleton of the run; detail is dim
#: because there is a great deal of it and it is only ever read in passing.
#:
#: The last four are not levels but *outcomes*, and they exist because at `-v`
#: the interesting question is not how much is happening but what kind: a
#: thousand dim lines all alike say a word was looked up and nothing about
#: whether it became a card. Green is a word that did, cyan is one that was
#: rescued into being one -- a misspelling corrected, a foreign word explained
#: -- yellow is one Wiktionary has no entry for, and magenta is one thrown away
#: on purpose. Scanning a run for magenta and finding a real word in it is how
#: a bad drop rule gets noticed.
_COLOURS = {
    "error": "\033[31m",
    "warn": "\033[33m",
    "head": "\033[1m",
    "info": "",
    "detail": "\033[2m",
    "bar": "\033[36m",
    "found": "\033[32m",
    "fixed": "\033[36m",
    "missing": "\033[33m\033[2m",
    "dropped": "\033[35m\033[2m",
}
_RESET = "\033[0m"
#: Erase the whole line and put the cursor back at its start.
_CLEAR = "\r\033[2K"

#: Seconds between the beats of the thread that redraws when the run does not.
#: Every other redraw is caused by the run saying something, which means a run
#: that says nothing -- a parse of a megabyte, a page fetched from a host that
#: is not answering, a model behind a tunnel that is down -- leaves the last
#: frame it drew standing on the terminal, clock and all, and is
#: indistinguishable from a run that has died. It also leaves the *previous*
#: frame rather than the last one: two lines logged within a fiftieth of a
#: second of each other are one redraw, the second line is held for a frame
#: that never comes, and what is on the terminal says the run stopped one step
#: before where it really stopped. That is what a Wiktionary mirror behind a
#: dead tunnel looked like on 2026-09-19: a screen that had not moved since the
#: parser finished loading, a run that was minutes past it, and no way to tell
#: either from a crash. Half a second is slow enough to cost nothing and fast
#: enough that the elapsed time reads as a clock rather than a stutter.
HEARTBEAT = 0.5

#: The four kinds that are outcomes rather than levels, tallied as they are
#: logged. They are counted before the level filter, so the screen's tally of
#: what became of the words is the same at every verbosity: at the default not
#: one of these lines is printed, and the counts are the only place the run
#: says how many words it rescued or threw away.
OUTCOMES = ("found", "fixed", "missing", "dropped")

#: How many log lines the screen keeps to replay on the way out. A run at `-v`
#: over a series logs a line per word, and the whole point of replaying is that
#: the terminal is left holding what a plain run would have left it: bounded,
#: because the alternative is holding a series' worth of strings for an hour to
#: print them once. A run that overflows it says so in the replay.
HISTORY = 20_000


def _duration(seconds: float | None) -> str:
    """A length of time as a person reads one, not as a float.

    Here rather than in `screen.py`, which is where it was written, because the
    bar wants it too now: both places the run shows its progress show the time
    it is taking, and they should not phrase it two ways.
    """
    if seconds is None:
        return "--"
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m{seconds % 60:02d}s"
    return f"{seconds // 3600}h{(seconds % 3600) // 60:02d}m"


@dataclass(frozen=True)
class Record:
    """One logged line, kept so the screen can redraw and replay it."""

    at: float
    kind: str
    message: str
    #: The word the line is about, when it is about one. The screen shows it
    #: in its own column; the plain renderer puts it in front of the message.
    word: str | None = None

    @property
    def plain(self) -> str:
        """The line as a redirected run writes it."""
        if self.word is None:
            return self.message
        return f"[decker] {self.word!r}: {self.message}"


@dataclass
class Stats:
    """What the run has made so far, for whoever is drawing a dashboard.

    A counter and nothing cleverer. Stages call :meth:`count` at the one place
    a thing comes into being -- a gloss is appended, a card is paired, a page
    is read -- rather than reporting a total at the end, because the number
    worth showing is the one that moves while the run is still going.
    """

    counts: Counter = field(default_factory=Counter)
    #: Seconds spent, by name. The model's is the one that matters: it is where
    #: a run's wall clock goes, and the only way to tell a cold run from a warm
    #: one without watching the clock.
    seconds: Counter = field(default_factory=Counter)

    def count(self, name: str, amount: int = 1) -> None:
        self.counts[name] += amount

    def spent(self, name: str, seconds: float) -> None:
        self.seconds[name] += seconds

    def __getitem__(self, name: str) -> int:
        return self.counts[name]

    def total(self, prefix: str) -> int:
        """Everything counted under ``prefix.``, added up."""
        return sum(
            count for name, count in self.counts.items()
            if name.startswith(f"{prefix}.")
        )


@dataclass
class Console:
    """Where decker's lines go, and how far along the run is."""

    level: int = NORMAL
    stream: object = field(default_factory=lambda: sys.stderr)
    phase_name: str = ""
    #: What the bar's numbers are counted in, for the dashboard to name. The
    #: bar itself still shows neither the count nor the unit -- see
    #: `docs/execution/the-console.md` -- because a number whose unit changes
    #: between phases explains nothing in a place that has no room to say what
    #: it is. The dashboard has the room and says it.
    unit: str = ""
    total: int = 0
    done: int = 0
    #: A second count, in whole things rather than in the phase's unit:
    #: sentences for a phase over a text, glosses for one over glosses. The
    #: bar advances by characters because sentences are not equal work; the
    #: dashboard says how many sentences that is, because that is the number a
    #: person has an intuition for.
    items: int = 0
    items_total: int = 0
    phase_started: float = 0.0
    started: float = field(default_factory=time.monotonic)
    stats: Stats = field(default_factory=Stats)
    #: The last :data:`HISTORY` lines, kept only while a screen is up.
    history: deque = field(default_factory=lambda: deque(maxlen=HISTORY))
    #: How many lines fell off the end of that.
    forgotten: int = 0
    #: The screen, while one is up. `None` is the plain path, unchanged.
    screen: object = None
    #: Whether a screen is wanted at all, when there is a terminal for one.
    wants_screen: bool = True
    #: What this run is, in a line, for the top of the screen: the languages,
    #: the model, the source. The command line knows all three and nothing
    #: else does, so it is set there rather than assembled here.
    headline: str = ""
    _drawn: bool = False
    _skip: bool = False
    _previous_handler: object = None
    #: Held while a line or a bar is being written, because the pulse below
    #: writes the bar from a thread of its own: without it a line logged
    #: halfway through a bar being drawn interleaves with it, and the terminal
    #: keeps both halves.
    _lock: object = field(default_factory=threading.RLock)
    #: Set to stop that thread.
    _resting: object = field(default_factory=threading.Event)

    @property
    def interactive(self) -> bool:
        """Whether the bar and the colour are wanted at all.

        `NO_COLOR` is honoured because it is the convention, and a stream that
        is not a terminal gets neither, because escape codes in a log file are
        noise and a bar in one is thousands of lines of it.
        """
        if os.environ.get("NO_COLOR"):
            return False
        isatty = getattr(self.stream, "isatty", None)
        return bool(isatty and isatty())

    def log(
        self,
        message: str,
        *,
        level: int = NORMAL,
        kind: str = "info",
        word: str | None = None,
    ) -> None:
        """One line, if this run is printing lines of that level.

        ``word`` is the term the line is about, when it is about one. It is
        passed rather than written into the message so that the two places a
        line is shown can lay it out their own way: the screen gives the word a
        column of its own beside the time, and a redirected run writes
        ``[decker] 'servilleta': 2 glosses``, which is what it always wrote.
        """
        if kind in OUTCOMES:
            #: Before the level check, deliberately: see :data:`OUTCOMES`.
            self.stats.count(f"word.{kind}")
        if level > self.level:
            return
        record = Record(at=time.time(), kind=kind, message=message, word=word)
        if self.screen is not None:
            if len(self.history) == self.history.maxlen:
                self.forgotten += 1
            self.history.append(record)
            self.screen.wrote(record)
            return
        colour = _COLOURS.get(kind, "") if self.interactive else ""
        end = _RESET if colour else ""
        with self._lock:
            self._erase()
            print(f"{colour}{record.plain}{end}", file=self.stream, flush=True)
            self._draw()

    @contextmanager
    def phase(
        self, name: str, total: int = 0, skippable: bool = True, unit: str = "",
        items: int = 0,
    ):
        """Name what the run is doing, and how much of it there is to do.

        The bar's units are the phase's own -- a phase over a text counts the
        text, a phase over titles counts titles -- and the bar shows neither,
        only the share done, because a number whose unit changes between phases
        explains nothing to the person reading it. ``unit`` names them for the
        dashboard, which has the room to say what it is counting, and ``items``
        is how many whole things that is: sentences, glosses, titles.

        A skippable phase catches `Ctrl+C` and stops *itself*, not the run: the
        loop inside asks :meth:`skipping` and breaks, and what the phase had
        done by then stands. A run is a long thing made of stages that each
        degrade gracefully -- glossing fewer words, parsing fewer titles -- and
        being unable to say "enough of this one" without losing the hour behind
        it is what makes a long run unusable. A second `Ctrl+C` stops the run,
        because the first must not take that away.
        """
        previous = (
            self.phase_name, self.total, self.done, self.unit,
            self.items, self.items_total, self.phase_started,
        )
        self.phase_name, self.total, self.done = name, total, 0
        self.unit, self.items, self.items_total = unit, 0, items
        self.phase_started = time.monotonic()
        self._skip = False
        if skippable:
            try:
                self._previous_handler = signal.signal(signal.SIGINT, self._interrupt)
            except ValueError:
                #: Not the main thread; there is nothing to install and the
                #: phase simply is not skippable.
                self._previous_handler = None
        self._draw()
        try:
            yield self
        finally:
            if skippable and self._previous_handler is not None:
                signal.signal(signal.SIGINT, self._previous_handler)
                self._previous_handler = None
            self._erase()
            if self._skip:
                self.log(f"[decker] {name} stopped early, carrying on with what it "
                         "had", kind="warn")
            self._skip = False
            (
                self.phase_name, self.total, self.done, self.unit,
                self.items, self.items_total, self.phase_started,
            ) = previous
            self._draw()

    def skipping(self) -> bool:
        """Whether the phase running now has been asked to stop."""
        return self._skip

    def _interrupt(self, signum: int, frame: object) -> None:
        """First `Ctrl+C` ends the phase; the second ends the run."""
        if self._skip:
            signal.signal(signal.SIGINT, self._previous_handler
                          or signal.default_int_handler)
            raise KeyboardInterrupt
        self._skip = True
        self.log(
            f"[decker] skipping {self.phase_name} -- Ctrl+C again to stop the run",
            level=QUIET, kind="warn",
        )

    def advance(self, amount: int = 1, items: int = 1) -> None:
        """Another `amount` of the phase is behind us."""
        self.done += amount
        self.items += items
        self._draw()

    @property
    def share(self) -> float:
        """How much of the phase is done, as a fraction of one."""
        return min(self.done / self.total, 1.0) if self.total else 0.0

    @property
    def remaining(self) -> float | None:
        """Seconds left in this phase at the rate it has run so far.

        `None` before there is a rate to speak of: an estimate made from the
        first half-second of a phase is a number that swings by minutes
        between redraws, which is worse than a blank.
        """
        if not self.total or not self.done or not self.phase_started:
            return None
        elapsed = time.monotonic() - self.phase_started
        if elapsed < 1.0:
            return None
        return elapsed * (self.total - self.done) / self.done

    def _draw(self) -> None:
        if self.screen is not None:
            self.screen.refresh()
            return
        if not self.interactive or self.level <= QUIET or not self.phase_name:
            return
        #: The share alone is a still picture: a phase that is waiting on a
        #: host that will not answer holds the same percentage for as long as
        #: it waits, and there is no way to tell that from a run that has
        #: stopped. So the bar carries a time as well -- what is left, once
        #: there is a rate to say it from, and how long this phase has been
        #: going before that -- and :meth:`pulse` redraws it while the run says
        #: nothing, which is the whole point of putting a clock there.
        remaining = self.remaining
        if remaining is None:
            elapsed = time.monotonic() - self.phase_started if self.phase_started else 0
            tail = f"{_duration(elapsed):>7}"
        else:
            tail = f"{_duration(remaining):>4} left"
        right = f"{self.share:4.0%}  {tail}"
        width = min(shutil.get_terminal_size((80, 24)).columns, 100)
        room = max(width - len(self.phase_name) - len(right) - 3, 8)
        filled = int(room * self.share)
        bar = "█" * filled + "░" * (room - filled)
        colour = _COLOURS["bar"]
        with self._lock:
            print(f"{_CLEAR}{colour}{self.phase_name} {bar} {right}{_RESET}",
                  file=self.stream, end="", flush=True)
            self._drawn = True

    def _erase(self) -> None:
        with self._lock:
            if self._drawn:
                print(_CLEAR, file=self.stream, end="", flush=True)
                self._drawn = False

    @contextmanager
    def pulsing(self):
        """Redraw the bar while the run is busy, when the bar is all there is.

        The screen has a heartbeat of its own; this is the same thing for the
        run that has no screen -- `--no-screen`, or a terminal too small for
        one -- where the bar is the only moving thing on the terminal and stops
        moving for exactly the stages a reader most wants to know are alive.
        Nothing is drawn between phases, so a run doing its parsing or its
        writing still shows a bare prompt; it is the phases that pulse.
        """
        if self.screen is not None or not self.interactive or self.level <= QUIET:
            yield
            return
        self._resting.clear()
        pulse = threading.Thread(target=self._pulse, daemon=True)
        pulse.start()
        try:
            yield
        finally:
            self._resting.set()
            pulse.join(timeout=HEARTBEAT * 4)

    def _pulse(self) -> None:
        while not self._resting.wait(HEARTBEAT):
            self._draw()

    @contextmanager
    def watching(self):
        """Draw the screen for the duration, if this run can have one.

        The whole run goes inside, the part that writes the output included:
        what a subcommand prints to stdout is held while the screen is up and
        let go once it is down, so `--format text` on a terminal reads the way
        it always did and no stage has to be taught to print somewhere else.
        Anything that cannot be drawn -- no `TERM`, a terminal too small, a
        curses that will not start -- is one line at `-vv` and the plain path.
        """
        if self.screen is not None or not self._may_draw():
            with self.pulsing():
                yield None
            return
        from decker.screen import Screen

        screen = Screen(self)
        try:
            screen.start()
        except Exception as error:  # no terminfo, a terminal too small, ...
            self.log(f"[decker] no screen this run ({error}); plain lines instead",
                     level=DETAIL, kind="detail")
            with self.pulsing():
                yield None
            return
        self.screen = screen
        try:
            yield screen
        finally:
            self.screen = None
            screen.stop()

    def _may_draw(self) -> bool:
        """Whether a screen is wanted, allowed and possible."""
        return bool(self.wants_screen and self.interactive and self.level > QUIET)


#: The one every stage writes to. A module-level singleton rather than a thing
#: passed down five call sites, because every stage prints and none of them
#: should have to be handed somewhere to print to.
console = Console()


def log(message: str, *, level: int = NORMAL, kind: str = "info",
        word: str | None = None) -> None:
    """Shorthand for `console.log`, which is what the stages call."""
    console.log(message, level=level, kind=kind, word=word)


def count(name: str, amount: int = 1) -> None:
    """Shorthand for `console.stats.count`, for the stages that only tally."""
    console.stats.count(name, amount)


def configure(verbose: int = 0, quiet: bool = False, screen: bool = True) -> None:
    """Set the level from the flags, once, before anything prints."""
    console.level = QUIET if quiet else min(NORMAL + verbose, DETAIL)
    console.wants_screen = screen

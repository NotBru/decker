"""One place decker speaks from: levels, colour, and a bar that stays put.

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

None of it happens when stderr is not a terminal: a redirected run writes plain
lines in order, which is what a file or a pipe wants, and what every measurement
in `docs/execution/` was taken from.
"""

from __future__ import annotations

import os
import shutil
import sys
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
_COLOURS = {
    "error": "\033[31m",
    "warn": "\033[33m",
    "head": "\033[1m",
    "info": "",
    "detail": "\033[2m",
    "bar": "\033[36m",
}
_RESET = "\033[0m"
#: Erase the whole line and put the cursor back at its start.
_CLEAR = "\r\033[2K"


@dataclass
class Console:
    """Where decker's lines go, and how far along the run is."""

    level: int = NORMAL
    stream: object = field(default_factory=lambda: sys.stderr)
    phase_name: str = ""
    total: int = 0
    done: int = 0
    _drawn: bool = False

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

    def log(self, message: str, *, level: int = NORMAL, kind: str = "info") -> None:
        """One line, if this run is printing lines of that level."""
        if level > self.level:
            return
        colour = _COLOURS.get(kind, "") if self.interactive else ""
        end = _RESET if colour else ""
        self._erase()
        print(f"{colour}{message}{end}", file=self.stream, flush=True)
        self._draw()

    @contextmanager
    def phase(self, name: str, total: int = 0):
        """Name what the run is doing, and how much of it there is to do.

        The bar's units are the phase's own -- a phase over a text counts the
        text, a phase over titles counts titles -- and the bar shows neither,
        only the share done, because a number whose unit changes between phases
        explains nothing to the person reading it.
        """
        previous = (self.phase_name, self.total, self.done)
        self.phase_name, self.total, self.done = name, total, 0
        self._draw()
        try:
            yield self
        finally:
            self._erase()
            self.phase_name, self.total, self.done = previous
            self._draw()

    def advance(self, amount: int = 1) -> None:
        """Another `amount` of the phase is behind us."""
        self.done += amount
        self._draw()

    def _draw(self) -> None:
        if not self.interactive or self.level <= QUIET or not self.phase_name:
            return
        width = min(shutil.get_terminal_size((80, 24)).columns, 100)
        share = min(self.done / self.total, 1.0) if self.total else 0.0
        room = max(width - len(self.phase_name) - 12, 8)
        filled = int(room * share)
        bar = "█" * filled + "░" * (room - filled)
        colour = _COLOURS["bar"]
        print(f"{_CLEAR}{colour}{self.phase_name} {bar} {share:4.0%}{_RESET}",
              file=self.stream, end="", flush=True)
        self._drawn = True

    def _erase(self) -> None:
        if self._drawn:
            print(_CLEAR, file=self.stream, end="", flush=True)
            self._drawn = False


#: The one every stage writes to. A module-level singleton rather than a thing
#: passed down five call sites, because every stage prints and none of them
#: should have to be handed somewhere to print to.
console = Console()


def log(message: str, *, level: int = NORMAL, kind: str = "info") -> None:
    """Shorthand for `console.log`, which is what the stages call."""
    console.log(message, level=level, kind=kind)


def configure(verbose: int = 0, quiet: bool = False) -> None:
    """Set the level from the flags, once, before anything prints."""
    console.level = QUIET if quiet else min(NORMAL + verbose, DETAIL)

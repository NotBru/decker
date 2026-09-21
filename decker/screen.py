"""The screen a run draws on a terminal: log on the left, tally on the right.

The bar told a run's reader how far along it was and nothing about what it was
making. At `-v` the log says what became of each word and scrolls too fast to
add up; at the default it says almost nothing and the deck's shape only appears
in the summary at the end, by which time the hour is spent. Both of those are
the same missing thing: a *running* answer to "what is this deck going to be".

So, when there is a terminal to draw on:

* **The log down the left**, one line per event, each stamped and headed by the
  word it is about, coloured by what became of that word -- the four outcomes
  `console.py` already distinguishes.
* **The tally down the right**, redrawn as it changes: how much text is left and
  how long that is likely to take, how many cards exist and of which kinds, what
  became of the words, and what the pages and the model have cost.
* **The bar along the bottom**, which is the old one, in the one place it was
  always drawn.

Three things about this file are decisions rather than mechanics, and are
written up in `docs/execution/the-console.md`: it draws on stderr's terminal
even when stdout is a file, it holds what the run writes to stdout until the
screen is down, and it replays the log as ordinary lines on the way out so a
finished run leaves the terminal holding what a plain run would have left it.
"""

from __future__ import annotations

import io
import locale
import os
import signal
import sys
import threading
import time
from dataclasses import dataclass, field

from decker.console import HEARTBEAT, _COLOURS, _RESET, Record, _duration

#: A screen is not worth drawing on a terminal this small: the dashboard alone
#: is thirty columns, and a log pane narrower than thirty more shows a word and
#: no room to say what happened to it. Below this the run falls back to the
#: plain lines and the one-line bar, which fit anywhere.
MINIMUM = (60, 10)

#: Below this the dashboard is dropped and the log takes the whole width. A
#: two-column layout that leaves fifteen columns for the log is worse at the
#: thing the log is for than one column is.
DASHBOARD_FROM = 76

#: How wide the dashboard is, when there is one. It is fixed rather than a
#: share of the width because its contents are fixed: a label and a number, and
#: the longest label is `already taught`.
DASHBOARD = 30

#: The time a log line carries, and how many columns that is. `[hh:mm:ss] `
#: is eleven; the width is written down rather than measured because the log
#: pane is laid out around it before there is a line to measure.
STAMP = "[%H:%M:%S] "
STAMP_WIDTH = 11

#: Redraws a second. The log is written a line per word and the bar advances a
#: sentence at a time, and at `-vv` both move faster than a terminal can paint;
#: past this the redraws cost more than the run's own work.
REDRAWS = 20.0


def _number(value: int) -> str:
    return f"{value:,}"


@dataclass
class Screen:
    """A curses screen over one run, and the terminal it borrowed to do it."""

    console: object
    _window: object = None
    _curses: object = None
    _pairs: dict = field(default_factory=dict)
    _saved_stdout_fd: int | None = None
    _saved_stderr_fd: int | None = None
    _real_stdout: object = None
    _captured: object = None
    #: The read end of the pipe fd 2 is pointed at while the screen is up, the
    #: thread reading it, and whether it has had anything to say.
    _foreign: int | None = None
    _listener: object = None
    _dirty: bool = False
    _previous_winch: object = None
    _resized: bool = False
    _last_drawn: float = 0.0
    _tty_input: bool = False
    #: Held for the whole of a redraw, because there are two threads that ask
    #: for one -- the run, and the heartbeat -- and curses is not reentrant:
    #: two `doupdate`s interleaved paint a frame made of halves of two.
    _lock: object = field(default_factory=threading.RLock)
    #: Set to stop the heartbeat, and waited on rather than slept through so
    #: that the thread ends when the screen does and not half a beat later.
    _stopping: object = field(default_factory=threading.Event)
    _beater: object = None

    # -- coming up, and going down -------------------------------------------

    def start(self) -> None:
        """Take the terminal, or raise and leave it exactly as it was.

        Raising is the only honest failure here: a half-initialized curses
        screen and a run still printing to it is a terminal nobody can read,
        so anything that goes wrong puts both descriptors back and hands the
        run to the plain path.
        """
        import curses

        if not os.environ.get("TERM"):
            raise RuntimeError("no TERM")
        self._curses = curses
        #: Asked before curses is started rather than after: a terminal too
        #: small for the layout should never have been switched to the
        #: alternate screen and back, which is a blink and, on some terminals,
        #: a cleared window.
        size = os.get_terminal_size(self.console.stream.fileno())
        if size.columns < MINIMUM[0] or size.lines < MINIMUM[1]:
            raise RuntimeError(f"terminal is {size.columns}x{size.lines}")
        #: Wide characters -- the bar's blocks, and every term in a language
        #: whose script is not Latin -- are what curses is being asked to
        #: draw, and it counts their width using the process's locale.
        try:
            locale.setlocale(locale.LC_ALL, "")
        except locale.Error:
            pass
        self._borrow_terminal()
        try:
            window = curses.initscr()
            curses.noecho()
            #: `cbreak`, never `raw`: raw would swallow `Ctrl+C`, and ending
            #: the phase with it is the one interaction a run already has.
            curses.cbreak()
            window.keypad(True)
            window.nodelay(True)
            try:
                curses.curs_set(0)
            except curses.error:
                pass  # a terminal that cannot hide its cursor still draws
            self._start_colour()
        except Exception:
            try:
                curses.endwin()
            except Exception:
                pass
            self._return_terminal()
            raise
        self._window = window
        #: Only when there is a terminal on the other end of it: the source
        #: text can arrive on stdin, and a screen reading keys off a pipe
        #: would be eating the document.
        self._tty_input = bool(sys.stdin and sys.stdin.isatty())
        self._watch_resize()
        self.refresh(force=True)
        self._beater = threading.Thread(target=self._beat, daemon=True)
        self._beater.start()

    def stop(self) -> None:
        """Give the terminal back, and leave the run's output behind in it."""
        #: Before curses is ended, and joined rather than only signalled: a
        #: beat landing after `endwin` draws on a terminal that is no longer
        #: the screen's, which is the run's own output overwritten by half a
        #: dashboard.
        self._stopping.set()
        if self._beater is not None:
            self._beater.join(timeout=HEARTBEAT * 4)
            self._beater = None
        if self._window is not None:
            try:
                self._curses.endwin()
            except Exception:
                pass
            self._window = None
        self._unwatch_resize()
        captured = self._return_terminal()
        self._replay()
        if captured:
            #: After the log, because that is the order they happened in and
            #: because this is the run's product: the cards of `--format text`
            #: should be the last thing on the terminal, not buried above the
            #: log they were built by.
            self._real_stdout.write(captured)
            self._real_stdout.flush()

    def _borrow_terminal(self) -> None:
        """Take both of the run's descriptors, and leave the terminal to curses.

        Two problems, and one answer to each.

        **stdout is not where the screen goes.** curses draws on fd 1 and
        cannot be told otherwise, and fd 1 is where `decker deck --format text
        > cards.txt` sends the deck. Drawing a screen into that file, or
        printing cards onto the screen, are the two ways of getting this
        wrong; the descriptor is borrowed for the duration, and what the run
        writes to stdout meanwhile is held and let go once the screen is down.

        **stderr is not only decker's.** Every line decker writes goes through
        the console, but stanza logs, urllib warns, and the tail of a Python
        warning arrives whenever it arrives. One such line scrolls the whole
        terminal up by a row, and from then on curses is drawing against a
        picture of the screen that is off by one: the frame tears and stays
        torn for the rest of the run, which is exactly what the first version
        of this file did. So fd 2 becomes a pipe, whatever comes out of it is
        drained into the log like any other line, and the terminal is left to
        curses alone.
        """
        stream = self.console.stream
        self._real_stdout = sys.stdout
        for handle in (sys.stdout, sys.stderr):
            try:
                handle.flush()
            except Exception:
                pass
        self._saved_stdout_fd = os.dup(1)
        os.dup2(stream.fileno(), 1)
        self._captured = io.StringIO()
        sys.stdout = self._captured
        self._saved_stderr_fd = os.dup(2)
        read, write = os.pipe()
        os.dup2(write, 2)
        os.close(write)
        self._foreign = read
        #: Read by a thread rather than between redraws: a pipe nobody is
        #: reading fills after sixty-odd kilobytes and then *blocks the
        #: writer*, and the writer is the run. Stanza downloading a model
        #: writes a progress bar for minutes during a single call that redraws
        #: nothing, which is exactly the shape that would hang.
        self._listener = threading.Thread(target=self._listen, daemon=True)
        self._listener.start()

    def _return_terminal(self) -> str:
        """Put both descriptors back, and return what stdout was given."""
        if self._saved_stderr_fd is not None:
            #: Restoring fd 2 closes the pipe's last writer, which is what
            #: ends the listener: it reads to the end of what was written and
            #: stops, so nothing sent while the screen was up is lost.
            try:
                os.dup2(self._saved_stderr_fd, 2)
                os.close(self._saved_stderr_fd)
            except OSError:
                pass
            self._saved_stderr_fd = None
        if self._listener is not None:
            self._listener.join(timeout=2.0)
            self._listener = None
        if self._foreign is not None:
            try:
                os.close(self._foreign)
            except OSError:
                pass
            self._foreign = None
        written = ""
        if self._captured is not None:
            written = self._captured.getvalue()
            self._captured = None
        if self._real_stdout is not None:
            sys.stdout = self._real_stdout
        if self._saved_stdout_fd is not None:
            try:
                os.dup2(self._saved_stdout_fd, 1)
                os.close(self._saved_stdout_fd)
            except OSError:
                pass
            self._saved_stdout_fd = None
        return written

    def _listen(self) -> None:
        """Put whatever else writes to stderr into the log, until nothing does.

        Appended to the history rather than logged, because this runs on a
        thread of its own and logging redraws. They are somebody else's lines,
        so they carry no word and the dim colour, and they are replayed on the
        way out with everything else -- a stanza warning is exactly the kind
        of thing a person goes looking for afterwards.
        """
        buffer = ""
        while self._foreign is not None:
            try:
                chunk = os.read(self._foreign, 1 << 16)
            except OSError:
                break
            if not chunk:
                break
            buffer += chunk.decode("utf-8", "replace")
            lines, _, buffer = buffer.rpartition("\n")
            if len(buffer) > 4096:
                #: Something is writing without newlines -- a progress bar
                #: carriage-returning over itself is the usual one -- and it
                #: is shown rather than held for the rest of the run.
                lines, buffer = f"{lines}\n{buffer}", ""
            self._foreign_lines(lines)
        self._foreign_lines(buffer)

    def _foreign_lines(self, text: str) -> None:
        for line in text.replace("\r", "\n").splitlines():
            if line.strip():
                self._remember(Record(at=time.time(), kind="detail",
                                      message=line.rstrip()))
                self._dirty = True

    def _remember(self, record: Record) -> None:
        """Keep a line the console did not write, the way the console keeps its own."""
        history = self.console.history
        if len(history) == history.maxlen:
            self.console.forgotten += 1
        history.append(record)

    def _start_colour(self) -> None:
        """One colour pair per kind of line, named the way the log names them."""
        curses = self._curses
        try:
            curses.start_color()
            curses.use_default_colors()
        except curses.error:
            return
        wanted = {
            "error": (curses.COLOR_RED, curses.A_BOLD),
            "warn": (curses.COLOR_YELLOW, 0),
            "head": (-1, curses.A_BOLD),
            "info": (-1, 0),
            "detail": (-1, curses.A_DIM),
            "bar": (curses.COLOR_CYAN, 0),
            "found": (curses.COLOR_GREEN, 0),
            "fixed": (curses.COLOR_CYAN, 0),
            "missing": (curses.COLOR_YELLOW, curses.A_DIM),
            "dropped": (curses.COLOR_MAGENTA, curses.A_DIM),
            "label": (-1, curses.A_DIM),
            "frame": (curses.COLOR_BLUE, curses.A_DIM),
        }
        for index, (kind, (colour, attribute)) in enumerate(wanted.items(), start=1):
            try:
                curses.init_pair(index, colour, -1)
            except curses.error:
                continue
            self._pairs[kind] = curses.color_pair(index) | attribute

    def _watch_resize(self) -> None:
        """Notice the terminal changing shape, without reading the keyboard."""
        try:
            self._previous_winch = signal.signal(signal.SIGWINCH, self._winch)
        except (ValueError, AttributeError):
            self._previous_winch = None

    def _unwatch_resize(self) -> None:
        if self._previous_winch is not None:
            try:
                signal.signal(signal.SIGWINCH, self._previous_winch)
            except ValueError:
                pass
            self._previous_winch = None

    def _winch(self, signum: int, frame: object) -> None:
        self._resized = True

    # -- what the console calls ----------------------------------------------

    def wrote(self, record: Record) -> None:
        """A line was logged. It is already in the console's history."""
        self.refresh()

    def _beat(self) -> None:
        """Redraw while the run is busy, until the screen comes down.

        The thread draws nothing of its own: it asks for the same redraw the
        run asks for, and everything on the screen is read from the console at
        draw time, so a beat during a stage that has not said anything picks up
        the clock, the elapsed time and whatever the stderr listener has
        caught, and a beat during a stage that is talking finds the throttle
        below and costs nothing.
        """
        while not self._stopping.wait(HEARTBEAT):
            self.refresh()

    def refresh(self, force: bool = False) -> None:
        """Redraw, unless one just happened.

        Everything the screen shows is read from the console at draw time, so
        a skipped redraw loses nothing: the heartbeat comes round within half a
        second and shows the same thing, and until it was there a skipped
        redraw was how the last line before a long stage went missing.
        """
        if self._window is None:
            return
        with self._lock:
            now = time.monotonic()
            if not force and now - self._last_drawn < 1.0 / REDRAWS:
                return
            self._last_drawn = now
            try:
                self._draw()
            except Exception:
                #: A screen that cannot draw must not be what ends a run that
                #: is otherwise working: the log and the tally are both
                #: recoverable on the way out, and the deck is not. The log is
                #: also being appended to by two other threads while this one
                #: reads it, so the rare frame lost to that is a frame the next
                #: beat draws again.
                pass

    # -- drawing -------------------------------------------------------------

    def _draw(self) -> None:
        curses, window = self._curses, self._window
        if self._resized:
            self._resized = False
            try:
                #: fd 1 is the terminal for the duration; stderr's own
                #: descriptor is a pipe by now.
                size = os.get_terminal_size(1)
                curses.resizeterm(size.lines, size.columns)
            except Exception:
                pass
            window.clear()
        if self._tty_input:
            #: Drain the keyboard so a held key cannot fill the buffer, and
            #: take `KEY_RESIZE` from it when the terminal sends one that way.
            while (key := window.getch()) != -1:
                if key == curses.KEY_RESIZE:
                    self._resized = True
        if self._dirty:
            #: Somebody else's line arrived. It was caught rather than printed,
            #: but a line that reached the terminal before the pipe was in
            #: place would have scrolled it, and then curses is diffing against
            #: a picture of the screen that is off by a row for the rest of the
            #: run. Painting the next frame in full costs a few kilobytes and
            #: is the only thing that repairs that.
            self._dirty = False
            window.clearok(True)
        window.erase()
        height, width = window.getmaxyx()
        dashboard = DASHBOARD if width >= DASHBOARD_FROM else 0
        log_width = width - dashboard - (1 if dashboard else 0)
        rows = range(1, height - 1)
        self._head(width)
        self._log(rows, log_width)
        if dashboard:
            for row in rows:
                self._put(row, log_width, "│", self._attribute("frame"))
            self._dashboard(rows, log_width + 1, dashboard)
        self._bar(height - 1, width)
        window.noutrefresh()
        curses.doupdate()

    def _put(self, row: int, column: int, text: str, attribute: int = 0,
             room: int | None = None) -> None:
        """Write `text` at one place, clipped, and never raise.

        `room` is the pane's width where there is a pane: clipping to the
        screen would let a long word of the log write over the divider and
        into the dashboard. curses also refuses to write the last cell of the
        screen -- the write succeeds and then the cursor cannot advance --
        which is a famous way of losing the bottom right corner of a layout to
        an exception.
        """
        height, width = self._window.getmaxyx()
        if not (0 <= row < height) or column >= width:
            return
        room = width - column if room is None else min(room, width - column)
        if row == height - 1:
            room = min(room, width - column - 1)
        if room <= 0:
            return
        try:
            self._window.addstr(row, column, _fit(text, room), attribute)
        except Exception:
            pass

    def _head(self, width: int) -> None:
        """The run, in a line: what is being built and how long it has taken."""
        console = self.console
        left = f" decker · {console.headline}" if console.headline else " decker"
        right = f"{_duration(time.monotonic() - console.started)} "
        line = _fit(left, max(width - len(right), 0))
        line = line.ljust(max(width - len(right), 0)) + right
        self._put(0, 0, line.ljust(width), self._attribute("head") | self._reverse())

    def _log(self, rows: range, width: int) -> None:
        """The tail of the log, wrapped, oldest at the top."""
        if width < STAMP_WIDTH + 8:
            return
        stamp_width = STAMP_WIDTH
        lines: list[tuple[str, str]] = []
        for record in list(self.console.history)[-len(rows):]:
            for piece in _lines(record, width, stamp_width):
                lines.append((record.kind, piece))
        for row, (kind, text) in zip(rows, lines[-len(rows):]):
            stamp, rest = text[:stamp_width], text[stamp_width:]
            self._put(row, 0, stamp, self._attribute("label"))
            self._put(row, stamp_width, rest, self._attribute(kind),
                      room=width - stamp_width)

    def _dashboard(self, rows: range, column: int, width: int) -> None:
        """The tally, top-aligned and clipped: the top rows are the ones kept.

        The sections are in the order a question about a run in progress
        arrives in -- when will it end, what is it making, what became of the
        words, what did it cost -- so a terminal too short for all of them
        keeps the ones asked first.
        """
        for row, (kind, label, value) in zip(rows, self.lines()):
            if kind == "gap":
                continue
            if kind == "head":
                self._put(row, column + 1, label.upper(), self._attribute("head"))
                continue
            room = width - 2
            value = _fit(value, room)
            label = _fit(label, max(room - len(value) - 1, 0))
            self._put(row, column + 1, label, self._attribute("label"))
            self._put(row, column + 1 + room - len(value), value,
                      self._attribute(kind))

    def _bar(self, row: int, width: int) -> None:
        """The old bar, in the place it was always drawn."""
        console = self.console
        #: One column short of the width: curses will not write the last cell
        #: of the last line, and a bar that ends in the corner would lose its
        #: last character to that rather than to any decision.
        width -= 1
        if not console.phase_name:
            self._put(row, 0, " " * width, self._reverse())
            return
        left = f" {console.phase_name} "
        right = f" {console.share:4.0%}  {_duration(console.remaining)} left "
        room = max(width - len(left) - len(right), 4)
        filled = int(room * console.share)
        bar = "█" * filled + "░" * (room - filled)
        self._put(row, 0, left, self._attribute("head") | self._reverse())
        self._put(row, len(left), bar, self._attribute("bar") | self._reverse())
        self._put(row, len(left) + room, right.ljust(width - len(left) - room),
                  self._attribute("head") | self._reverse())

    def _attribute(self, kind: str) -> int:
        return self._pairs.get(kind, 0)

    def _reverse(self) -> int:
        return self._curses.A_REVERSE if self._curses else 0

    # -- what the dashboard says ---------------------------------------------

    def lines(self) -> list[tuple[str, str, str]]:
        """The dashboard's rows, as `(kind, label, value)`.

        Built here rather than drawn directly so the same list can be printed
        as plain lines when the screen comes down: the summary a finished run
        leaves behind should be the thing that was on the screen a moment
        before, not a second account of it written separately.
        """
        console, stats = self.console, self.console.stats
        rows: list[tuple[str, str, str]] = []

        rows.append(("head", "run", ""))
        rows.append(("info", "elapsed", _duration(time.monotonic() - console.started)))
        if console.phase_name:
            rows.append(("info", "phase", console.phase_name))
            rows.append(("bar", "left", _duration(console.remaining)))
            if console.total:
                unit = console.unit or "done"
                rows.append((
                    "info", unit,
                    f"{_number(max(console.total - console.done, 0))} left",
                ))
            if console.items_total:
                rows.append(("detail", "  of",
                             f"{_number(console.items)}/{_number(console.items_total)}"))
        rows.append(("gap", "", ""))

        cards = stats.total("card")
        rows.append(("head", "cards", ""))
        rows.append(("found", "built", _number(cards)))
        rows.append(("detail", "  recognition", _number(stats["card.recognition"])))
        rows.append(("detail", "  production", _number(stats["card.production"])))
        rows.append(("gap", "", ""))

        rows.append(("head", "glosses", ""))
        rows.append(("found", "made", _number(stats.total("gloss"))))
        for name, label in (
            ("word", "  words"),
            ("concept", "  concepts"),
            ("rule", "  rules"),
            ("symbol", "  symbols"),
            ("foreign", "  foreign"),
        ):
            if stats[f"gloss.{name}"]:
                rows.append(("detail", label, _number(stats[f"gloss.{name}"])))
        if stats["gloss.known"]:
            rows.append(("dropped", "  already taught", _number(stats["gloss.known"])))
        rows.append(("gap", "", ""))

        rows.append(("head", "words", ""))
        for name, label in (
            ("found", "found"),
            ("fixed", "rescued"),
            ("missing", "no entry"),
            ("dropped", "dropped"),
        ):
            rows.append((name, label, _number(stats[f"word.{name}"])))
        rows.append(("gap", "", ""))

        rows.append(("head", "cost", ""))
        rows.append(("detail", "pages fetched", _number(stats["page.fetched"])))
        rows.append(("detail", "pages cached", _number(stats["page.cached"])))
        if stats["page.failed"]:
            rows.append(("error", "pages failed", _number(stats["page.failed"])))
        rows.append(("detail", "model asked", _number(stats["model.asked"])))
        rows.append(("detail", "model remembered", _number(stats["model.remembered"])))
        rows.append(("bar", "model time", _duration(stats.seconds["model"])))
        return rows

    # -- the way out ----------------------------------------------------------

    def _replay(self) -> None:
        """Print the log, then the tally, as a plain run would have printed them.

        A screen that vanishes takes the run with it: the word that could not
        be fetched, the sense that was dropped, the warning in the middle of
        an hour. So what was on it is written to the terminal it gave back, in
        the colours the plain path uses, and the terminal's own scrollback --
        which is the thing a person actually searches -- holds the run.
        """
        stream = self.console.stream
        colour = not os.environ.get("NO_COLOR")
        if self.console.forgotten:
            self._line(
                stream, colour, "warn",
                f"[decker] {_number(self.console.forgotten)} earlier lines "
                "scrolled off the screen and are not repeated here "
                "(--no-screen keeps all of them)",
            )
        for record in self.console.history:
            self._line(stream, colour, record.kind, record.plain)
        for kind, label, value in self.lines():
            if kind == "gap":
                continue
            if kind == "head":
                self._line(stream, colour, "head", f"[decker] {label}")
                continue
            self._line(stream, colour, kind,
                       f"[decker]   {label.strip().ljust(18)}{value}")
        stream.flush()

    @staticmethod
    def _line(stream, colour: bool, kind: str, text: str) -> None:
        start = _COLOURS.get(kind, "") if colour else ""
        print(f"{start}{text}{_RESET if start else ''}", file=stream)


def _lines(record: Record, width: int, stamp_width: int) -> list[str]:
    """One log record as the lines it takes up in a pane `width` wide.

    The format is the one the eye scans down: the time, the word it is about,
    and what happened to it. A line about no word in particular -- a stage
    heading, a warning about the run itself -- keeps the whole width for its
    message, since there is nothing to line up with.
    """
    stamp = time.strftime(STAMP, time.localtime(record.at))
    message = record.message
    if message.startswith("[decker] "):
        #: The stages write the prefix because a redirected run's lines land
        #: among other programs' and have to say whose they are. Every line
        #: here is decker's.
        message = message[len("[decker] "):]
    head = f"{record.word}: " if record.word else ""
    room = max(width - stamp_width, 8)
    wrapped = _wrap(head + message.strip(), room)
    if not wrapped:
        return []
    lines = [stamp + wrapped[0]]
    #: Continuations sit under the message rather than under the time, so a
    #: column of timestamps stays a column.
    lines.extend(" " * stamp_width + piece for piece in wrapped[1:])
    return lines


def _wrap(text: str, width: int) -> list[str]:
    """`text` in lines of at most `width`, broken at spaces where it can be."""
    lines: list[str] = []
    for paragraph in text.splitlines() or [""]:
        while len(paragraph) > width:
            cut = paragraph.rfind(" ", 0, width + 1)
            if cut <= 0:
                cut = width
            lines.append(paragraph[:cut])
            paragraph = paragraph[cut:].lstrip()
        lines.append(paragraph)
    return lines


def _fit(text: str, width: int) -> str:
    """`text`, cut to `width` with an ellipsis when it does not fit."""
    if width <= 0:
        return ""
    if len(text) <= width:
        return text
    if width == 1:
        return "…"
    return text[: width - 1] + "…"

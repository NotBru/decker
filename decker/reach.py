"""Waiting out a remote that stopped answering, instead of going without it.

A run depends on two remotes it does not control: an ollama host, often at the
far end of a tunnel, and a Wiktionary, Wikimedia's or a mirror. Either can drop
for a minute -- a laptop's wifi, a tunnel re-establishing, a server restart --
and before this a drop *changed the run*: a question that could not be asked
kept every sense, a page that could not be fetched was a gloss the deck went
without, and a mirror that did not answer read as a mirror without the
glossary, so the run switched source. A four-hour run that lost the tunnel for
a minute at its start finished as a different deck, and said so once, in a
line that had long scrolled away.

So connectivity is no longer a reason for a result. A caller that fails to
reach a remote asks its `Gate` to wait, and the gate holds every thread that
needs that remote until a probe gets through, logging when it went and when it
came back. The request is then made again, as if nothing had happened. What
still degrades a run is the remote *answering* something unusable -- a model
that is not there, a page that does not exist -- which is a fact about the
setup rather than about the network, and is reported as before.

See docs/execution/connectivity.md.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable

from decker.console import VERBOSE, console, count, log

#: The first wait between probes, and the ceiling it doubles up to. A tunnel
#: coming back is noticed within half a minute without probing a dead host
#: several times a second.
FIRST_DELAY = 2.0
MAX_DELAY = 10.0

#: How often a wait that is still going says so. Without it a long outage is
#: one line and then silence, which reads the same as a hung run.
REMINDER = 300.0

#: How many times a request that failed while its remote was reachable is made
#: again before the caller treats the failure as the request's own. Those are
#: the blips a probe arrives too late to see -- a connection reset by a tunnel
#: that is already back -- and the request's fault after that.
BLIPS = 3


#: Every outage waited out this run, by remote: how many, and for how long in
#: all. Read back by `report`, so a run that lost its tunnel says so in its
#: last lines and not only in one that scrolled away hours before.
_OUTAGES: dict[str, tuple[int, float]] = {}
_OUTAGES_LOCK = threading.Lock()


def report() -> None:
    """Say which remotes dropped since the last report, and what it cost in time.

    Called at the end of each stage that talks to a remote -- glossing, and the
    cards' translation -- so each outage is said once, by the stage it held up.
    """
    with _OUTAGES_LOCK:
        items = sorted(_OUTAGES.items())
        _OUTAGES.clear()
    if not items:
        return
    parts = ", ".join(
        f"{name} {outages} time{'s' if outages != 1 else ''} ({_duration(total)})"
        for name, (outages, total) in items
    )
    log(f"[decker] waited out outages, deck unaffected: {parts}", kind="warn")


def _duration(seconds: float) -> str:
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m{seconds % 60:02d}s"
    return f"{seconds // 3600}h{seconds % 3600 // 60:02d}m"


class Gate:
    """One remote, and the wait every thread shares while it is down.

    ``probe`` is a cheap request that says whether the remote answers at all;
    it is only ever called by the one thread leading a wait, so an outage is
    probed once every few seconds however many threads are held by it.
    """

    def __init__(self, name: str, probe: Callable[[], bool]) -> None:
        self.name = name
        self.probe = probe
        self._lock = threading.Lock()
        self._back: threading.Event | None = None

    def wait(self, reason: str) -> bool:
        """Hold until the remote answers again.

        Returns whether it had been down, which is to say whether the failure
        was the remote's. ``False`` means the probe got straight through: the
        failure was a blip or the request's own, and the caller decides which
        by how often it recurs.
        """
        with self._lock:
            back = self._back
            if back is None:
                back = self._back = threading.Event()
                leading = True
            else:
                leading = False
        if not leading:
            #: In slices, so Ctrl+C is not held up behind the other thread.
            while not back.wait(1.0):
                pass
            return True
        try:
            return self._lead(reason)
        finally:
            with self._lock:
                self._back = None
            back.set()

    def _lead(self, reason: str) -> bool:
        if self._safe_probe():
            log(f"[decker] {self.name}: {reason}; it answers, so asking again",
                level=VERBOSE, kind="warn")
            count(f"reach.{self.name}.blips")
            return False
        started = time.monotonic()
        count(f"reach.{self.name}.outages")
        log(f"[decker] {self.name} unreachable ({reason}); waiting for it, "
            "the run carries on unchanged once it answers", kind="error")
        delay = FIRST_DELAY
        reminder = started + REMINDER
        told = False
        while True:
            time.sleep(delay)
            if self._safe_probe():
                break
            if console.skipping() and not told:
                #: A phase ends between terms, and this term is still waiting,
                #: so the first Ctrl+C cannot take effect until the remote is
                #: back. The second one stops the run at once, as always.
                told = True
                log(f"[decker] the skip takes effect once {self.name} answers; "
                    "Ctrl+C again to stop the run now", kind="warn")
            delay = min(delay * 2, MAX_DELAY)
            if time.monotonic() >= reminder:
                reminder += REMINDER
                log(f"[decker] {self.name} still unreachable after "
                    f"{_duration(time.monotonic() - started)}; still waiting",
                    kind="error")
        waited = time.monotonic() - started
        log(f"[decker] {self.name} reachable again after "
            f"{_duration(waited)}; carrying on", kind="warn")
        with _OUTAGES_LOCK:
            outages, total = _OUTAGES.get(self.name, (0, 0.0))
            _OUTAGES[self.name] = (outages + 1, total + waited)
        return True

    def _safe_probe(self) -> bool:
        try:
            return bool(self.probe())
        except Exception:
            return False


_HTTP_GATES: dict[tuple[str, str], Gate] = {}
_HTTP_GATES_LOCK = threading.Lock()

#: What a MediaWiki is asked to prove it is up: the cheapest query its API
#: answers. The API and not the front page, because in a Wikimedia outage the
#: caches can go on serving the front page's redirect while every API call
#: comes back 503, and it is the API a run needs.
_API_PROBE = "/w/api.php?action=query&meta=siteinfo&format=json"


def http_gate(url: str, user_agent: str) -> Gate:
    """The gate for the origin a URL is on, one per origin for the whole run.

    A MediaWiki is probed at its API and anything else -- the upload host the
    recordings are on, the dumps -- at its root. Any status under 500 is an
    answer: a 404 or a redirect is a server that is there.
    """
    import http.client
    import urllib.parse

    parts = urllib.parse.urlsplit(url)
    key = (parts.scheme, parts.netloc)
    with _HTTP_GATES_LOCK:
        if key not in _HTTP_GATES:
            path = _API_PROBE if parts.path.startswith("/w/api.php") else "/"

            def probe() -> bool:
                opener = (
                    http.client.HTTPSConnection if parts.scheme == "https"
                    else http.client.HTTPConnection
                )
                connection = opener(parts.netloc, timeout=10)
                try:
                    connection.request("GET", path, headers={"User-Agent": user_agent})
                    return connection.getresponse().status < 500
                finally:
                    connection.close()

            _HTTP_GATES[key] = Gate(f"{parts.scheme}://{parts.netloc}", probe)
        return _HTTP_GATES[key]

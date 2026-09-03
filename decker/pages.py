"""Wiktionary pages: fetching, caching, and the pieces a gloss is made of.

Two endpoints are read per title. The REST definition endpoint keys its
entries by language code and renders form-of definitions in full, which is
what an inflected term needs; the parse endpoint's HTML is where etymology,
IPA and audio live. Both payloads are cached verbatim, one gzipped file per
title, so a page is fetched once however many terms land on it. Audio is not
part of that cache: the page keeps the URL, and the sound file is downloaded
next to it only when asked for.
"""

from __future__ import annotations

import gzip
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, replace
from html.parser import HTMLParser
from pathlib import Path

from decker.languages import name_of
from decker.wiktionary import USER_AGENT, cache_dir

#: Where the pages are asked for. A local mirror answers the same paths under
#: a different origin, so a whole run can be pointed at one by naming it --
#: see `docs/execution/local-wiktionary.md`. The edition still picks the host
#: when no origin is given, since only Wikimedia has one host per edition.
HOST_VARIABLE = "DECKER_WIKTIONARY_HOST"
DEFAULT_ORIGIN = "https://{edition}.wiktionary.org"
HOST: str | None = os.environ.get(HOST_VARIABLE)

PARSE_PATH = (
    "/w/api.php?action=parse&page={title}&prop=text&formatversion=2&format=json"
)


def origin(edition: str) -> str:
    """The origin a page is fetched from."""
    return (HOST or DEFAULT_ORIGIN.format(edition=edition)).rstrip("/")

#: What joins an example sentence to its rendering when something shows the
#: two together. It is only ever written, never read back: the halves travel
#: apart all the way to the card, so a sentence carrying the separator itself
#: -- eight of the examples in a warm cache do -- is no longer something
#: decker can cut in the wrong place.
EXAMPLE_SEPARATOR = " — "

#: IPA spans hold rhymes and syllabifications too; only these are a reading.
_IPA_DELIMITERS = ("/", "[")

#: Wikimedia throttles unauthenticated callers, so requests are paced and a
#: refusal is waited out rather than dropped.
MIN_INTERVAL = 0.5
MAX_ATTEMPTS = 5
BACKOFF = 2.0

_last_request = 0.0

_IPA = re.compile(r'<span class="IPA[^"]*">([^<]+)</span>')
_AUDIO = re.compile(r'src="(//upload\.wikimedia\.org/[^"]+\.(?:ogg|oga|mp3|wav))"')
_SECTION = re.compile(r'<h2 id="([^"]+)"')
_ETYMOLOGY_HEADING = re.compile(r'<h[34] id="Etymology[^"]*"')
_PARAGRAPH = re.compile(r"<p\b[^>]*>(.*?)</p>", re.DOTALL)


@dataclass(frozen=True)
class Example:
    """One example sentence, and the edition's rendering of it if it has one.

    The halves answer to different rules -- the sentence is the target
    language and is the very thing a card teaches, the rendering is the
    edition's prose and is the only half a translator may touch -- so they are
    kept apart while they are data and joined only where they are shown.
    """

    #: The example itself, in the language being taught.
    sentence: str
    #: The edition's rendering of it, when Wiktionary carries one.
    rendering: str | None = None

    def __str__(self) -> str:
        """The pair as a card, a document or the terminal shows it."""
        if self.rendering is None:
            return self.sentence
        return f"{self.sentence}{EXAMPLE_SEPARATOR}{self.rendering}"


@dataclass(frozen=True)
class Sense:
    """One numbered definition of a page, with the examples under it."""

    definition: str
    examples: tuple[Example, ...] = ()


@dataclass(frozen=True)
class Entry:
    """One part of speech of one language on a page."""

    language: str
    part_of_speech: str
    senses: tuple[Sense, ...]


@dataclass(frozen=True)
class Page:
    """A Wiktionary page, cut down to one language."""

    title: str
    language: str
    entries: tuple[Entry, ...] = ()
    etymology: str | None = None
    ipa: tuple[str, ...] = ()
    #: Every recording the language section offers, in the order it lists
    #: them. A page can carry several -- `el` has one for Spain and one for
    #: Colombia -- and which of them a learner wants is not decker's to guess.
    audio_urls: tuple[str, ...] = ()

    @property
    def senses(self) -> list[tuple[str, Sense]]:
        """Every sense of the page, each with the part of speech it sits under."""
        return [
            (entry.part_of_speech, sense)
            for entry in self.entries
            for sense in entry.senses
        ]


class _Stripper(HTMLParser):
    """Turn a fragment of Wiktionary's HTML into plain text."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)

    def text(self) -> str:
        return re.sub(r"\s+", " ", "".join(self.parts)).strip()


def strip_html(fragment: str) -> str:
    stripper = _Stripper()
    stripper.feed(fragment)
    return stripper.text()


def pages_dir(edition: str) -> str:
    """The cache directory for one edition, per source.

    A page from a mirror and a page from Wikimedia are not interchangeable --
    the mirror's carries no media, since no dump does -- so they cannot share
    a file. Keyed only by title, a refresh against one silently replaced the
    other, and a deck built afterwards lost its audio without anything saying
    so. The default source keeps the plain name, so nothing already cached
    moves.
    """
    if not HOST:
        return f"pages-{edition}"
    return f"pages-{edition}@{re.sub(r'[^\w.\-]', '_', HOST)}"


def page_cache_path(title: str, edition: str) -> Path:
    """Where a title's raw payloads are kept.

    Titles are quoted, so a title carrying a slash or a colon cannot escape
    the directory or collide with another.
    """
    safe = urllib.parse.quote(title, safe="")
    return cache_dir() / pages_dir(edition) / f"{safe}.json.gz"


def fetch(title: str, *, edition: str, lang: str, refresh: bool = False) -> Page | None:
    """Return ``title``'s page as far as ``lang`` is concerned.

    ``None`` when the page does not exist, or exists without a section for
    the language -- an ordinary outcome, since a title may be spelled the
    same in a language the source text is not written in.
    """
    payloads = _payloads(title, edition=edition, refresh=refresh)
    if payloads is None:
        return None
    language = name_of(lang)
    entries = _entries_from_html(payloads.get("parse"), language)
    if not entries and _is_split(payloads):
        payloads, entries = _from_split(title, payloads, edition=edition, lang=lang, refresh=refresh)
    if not entries:
        return None
    language = entries[0].language or language
    etymology, ipa, audios = _from_html(payloads.get("parse"), language)
    return Page(
        title=title,
        language=language,
        entries=tuple(entries),
        etymology=etymology,
        ipa=ipa,
        audio_urls=audios,
    )


#: Wiktionary moves the language sections of an oversized page onto subpages
#: and leaves this footer behind in their place.
_SPLIT_MARKER = "mammoth-page-footer"

#: The two subpages it splits them into, by the language's English name.
_SPLIT_SUBPAGES = ("{title}/languages A to L", "{title}/languages M to Z")


def _is_split(payloads: dict) -> bool:
    """Whether this page keeps its language sections on subpages.

    `a` carries hundreds of languages, so Wiktionary renders only Translingual
    and English and replaces the rest with a footer of links. Every endpoint
    agrees -- the definition API returns `en` alone and the raw wikitext has no
    `==Spanish==` -- so this is not truncation to work around but a split to
    follow, and the sections really are somewhere else.
    """
    parse = payloads.get("parse")
    if not isinstance(parse, dict):
        return False
    return _SPLIT_MARKER in parse.get("parse", {}).get("text", "")


def _from_split(
    title: str, payloads: dict, *, edition: str, lang: str, refresh: bool
) -> tuple[dict, list]:
    """Look for ``lang`` on the subpages a split page hands its sections to.

    Which of the two holds it depends on the language's English name, which is
    not what we are given, so both are tried. The payloads of whichever one
    answers are returned with it, since the etymology and the reading have to
    come from the same place as the definitions.
    """
    for pattern in _SPLIT_SUBPAGES:
        subpage = pattern.format(title=title)
        found = _payloads(subpage, edition=edition, refresh=refresh)
        if found is None:
            continue
        entries = _entries_from_html(found.get("parse"), name_of(lang))
        if entries:
            return found, entries
    return payloads, []


def _payloads(title: str, *, edition: str, refresh: bool) -> dict | None:
    """The two raw responses for a title, from cache or from the network."""
    path = page_cache_path(title, edition)
    if path.exists() and not refresh:
        with gzip.open(path, "rt", encoding="utf-8") as cached:
            return json.load(cached)

    quoted = urllib.parse.quote(title, safe="")
    base = origin(edition)
    #: The rendered page is what the senses are read from, so it decides
    #: whether the title exists at all. The REST payload is asked for second
    #: and tolerated missing: a mirror does not serve that endpoint, and
    #: nothing needs it unless the render failed to arrive.
    parse = _get_json(base + PARSE_PATH.format(title=quoted))
    if parse is None:
        return None
    payloads = {"parse": parse}

    if _transient_failure(parse):
        #: Wiktionary renders a Lua timeout *into the page*, with a 200 and a
        #: well-formed body, so nothing below this notices that the
        #: definitions are error text. Cached, it is permanent: every later
        #: run reads the file and asks the model to choose between fifteen
        #: copies of the same message. `de` and `o` were both caught this way.
        #: The page is still returned -- a degraded run beats no run -- but it
        #: is not written, so the next run has a chance at the real thing.
        print(
            f"[decker] {title!r} came back as a Wiktionary error page; "
            "using it once, not caching it",
            file=sys.stderr,
        )
        return payloads

    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as out:
        json.dump(payloads, out, ensure_ascii=False)
    return payloads


#: Wiktionary's server-side failures that come back as page text under a 200.
_TRANSIENT = (
    "The time allocated for running Lua modules has expired",
    "Lua error",
    "script error",
)


def _transient_failure(definition: object) -> bool:
    """Whether a definition payload is Wiktionary reporting its own failure."""
    text = json.dumps(definition, ensure_ascii=False).lower()
    return any(marker.lower() in text for marker in _TRANSIENT)


class Refused(Exception):
    """Wikimedia refused the client itself, rather than the resource asked for.

    A 403 is not a page that is missing (404) and not a rate limit that will
    pass (429): it is the request being turned away, almost always over the
    User-Agent policy or an IP block. Nothing later in the run will fare any
    better, so this is raised rather than counted, and the run stops on the
    first one instead of scrolling hundreds of them and finishing with a
    suspiciously thin deck.
    """


#: Fetches that gave up, by kind. A page decker cannot get is a gloss it
#: cannot make, and until these were counted the only way to notice was to
#: read the deck and find it thin.
FAILURES: Counter[str] = Counter()


def report() -> None:
    """Say how many fetches failed, if any did."""
    if not FAILURES:
        return
    parts = ", ".join(f"{count} {kind}" for kind, count in sorted(FAILURES.items()))
    print(
        f"[decker] {sum(FAILURES.values())} fetches failed: {parts}",
        file=sys.stderr,
    )


def _fetch(
    url: str,
    *,
    what: str = "request",
    quiet: bool = False,
    decode: Callable[[bytes], object] | None = None,
) -> object:
    """One request, paced with every other, waiting out throttling.

    Everything decker asks Wikimedia for goes through here -- API payloads and
    sound files alike -- because the rate limit counts them together. Audio
    used to have its own one-shot download with no pacing and no retry, which
    is how a single run collected eighteen `429 Your bot is making too many
    requests` and silently dropped the files.
    """
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    for attempt in range(MAX_ATTEMPTS):
        _pace()
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                body = response.read()
            return body if decode is None else decode(body)
        except urllib.error.HTTPError as error:
            if error.code == 404:
                return None
            if error.code == 403:
                raise Refused(url) from error
            if error.code not in (429, 503) or attempt == MAX_ATTEMPTS - 1:
                if not quiet:
                    print(f"[decker] {url}: HTTP {error.code}", file=sys.stderr)
                    FAILURES[f"{what}: HTTP {error.code}"] += 1
                return None
            time.sleep(_retry_after(error, attempt))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
            if attempt == MAX_ATTEMPTS - 1:
                if not quiet:
                    print(f"[decker] {url}: {error}", file=sys.stderr)
                    FAILURES[f"{what}: unreachable"] += 1
                return None
            time.sleep(BACKOFF**attempt)
    return None


def _get_json(url: str, *, quiet: bool = False) -> dict | list | None:
    """Fetch and decode one API response, waiting out throttling."""
    answer = _fetch(
        url, what="page", quiet=quiet, decode=lambda body: json.loads(body.decode("utf-8"))
    )
    return answer if isinstance(answer, (dict, list)) else None


def _pace() -> None:
    """Keep a floor between one request and the next."""
    global _last_request
    wait = _last_request + MIN_INTERVAL - time.monotonic()
    if wait > 0:
        time.sleep(wait)
    _last_request = time.monotonic()


def _retry_after(error: urllib.error.HTTPError, attempt: int) -> float:
    """How long the server asked us to wait, or a widening guess."""
    header = error.headers.get("Retry-After") if error.headers else None
    if header:
        try:
            return min(float(header), 60.0)
        except ValueError:
            pass
    return BACKOFF**attempt


def _from_html(
    parse: dict | None, language: str
) -> tuple[str | None, tuple[str, ...], tuple[str, ...]]:
    """Pull etymology, IPA and every recording out of the rendered page."""
    if not isinstance(parse, dict):
        return None, (), ()
    html = parse.get("parse", {}).get("text")
    if not isinstance(html, str):
        return None, (), ()
    section = _language_section(html, language)
    if section is None:
        return None, (), ()

    ipa = tuple(
        reading
        for raw in _IPA.findall(section)
        if (reading := strip_html(raw)).startswith(_IPA_DELIMITERS)
    )
    return _etymology(section), ipa, _audios(section)


def _audios(section: str) -> tuple[str, ...]:
    """Every recording the section offers, one file apiece, in page order.

    Every recording, because a section that lists two has two to give: `el`
    carries one for Spain and one for Colombia, and which of them a learner
    wants is not decker's to guess. One file apiece, because Wikimedia
    transcodes each recording into several formats -- the same clip arrives as
    both `.ogg` and `.mp3` -- and those are one recording, not two; a card
    holding both would simply play it twice. The transcodes of a recording
    share everything but that last extension, which is what they are grouped
    on, and `.ogg` is the one kept: it is the format the source is served as.
    """
    recordings: dict[str, str] = {}
    for match in _AUDIO.finditer(section):
        url = f"https:{match.group(1)}"
        recording, _, extension = url.rpartition(".")
        if recording not in recordings or extension == "ogg":
            recordings[recording] = url
    return tuple(recordings.values())


#: Wiktionary renders its structure and the REST definition endpoint flattens
#: it, so the senses are read from the page itself. A heading names a part of
#: speech, the list under it holds one sense per item, and an example arrives
#: as its own elements -- `e-example` for the sentence, `e-translation` for the
#: rendering -- rather than as one string to be cut apart. Sub-senses are
#: nested where the payload made them siblings, which is what once cost the
#: lemma of an inflected form.
_VOID = frozenset(
    ("br", "img", "hr", "meta", "link", "input", "source", "track", "wbr", "col")
)

#: Headings whose list is not a list of senses.
_NOT_SENSES = frozenset(
    (
        "references", "further reading", "anagrams", "quotations", "descendants",
        "translations", "derived terms", "related terms", "see also", "usage notes",
        "alternative forms", "conjugation", "declension", "inflection", "pronunciation",
        "etymology", "synonyms", "antonyms", "hypernyms", "hyponyms", "holonyms",
        "meronyms", "coordinate terms", "statistics", "trivia", "gallery", "notes",
        "external links", "sources", "citations",
    )
)


class _Tree(HTMLParser):
    """The smallest tree that lets a sense list be walked rather than matched."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root: dict = {"tag": None, "attrs": {}, "children": []}
        self._stack = [self.root]

    def handle_starttag(self, tag, attrs):
        node = {"tag": tag, "attrs": dict(attrs), "children": []}
        self._stack[-1]["children"].append(node)
        if tag not in _VOID:
            self._stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self._stack[-1]["children"].append(
            {"tag": tag, "attrs": dict(attrs), "children": []}
        )

    def handle_endtag(self, tag):
        for depth in range(len(self._stack) - 1, 0, -1):
            if self._stack[depth]["tag"] == tag:
                del self._stack[depth:]
                return

    def handle_data(self, data):
        self._stack[-1]["children"].append(data)


def _parse_tree(html: str) -> dict:
    tree = _Tree()
    tree.feed(html)
    return tree.root


def _classes(node: dict) -> set[str]:
    return set((node.get("attrs", {}).get("class") or "").split())


def _text(node, *, skip=()) -> str:
    """The text under a node, leaving out whole subtrees by tag."""
    if isinstance(node, str):
        return node
    if node.get("tag") in skip:
        return ""
    return "".join(_text(child, skip=skip) for child in node["children"])


def _tidy(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip(" \t\n:;,")


def _find(node, predicate, found=None) -> list:
    """Every node under this one that the predicate likes, in order."""
    found = [] if found is None else found
    for child in node["children"] if not isinstance(node, str) else ():
        if isinstance(child, str):
            continue
        if predicate(child):
            found.append(child)
        _find(child, predicate, found)
    return found


def _html_examples(item: dict) -> list[Example]:
    """The usage examples under one sense, each as its own two halves."""
    examples = []
    for block in _find(item, lambda n: "h-usage-example" in _classes(n)):
        sentence = next(
            (_tidy(_text(n)) for n in _find(block, lambda n: "e-example" in _classes(n))),
            "",
        )
        rendering = next(
            (_tidy(_text(n)) for n in _find(block, lambda n: "e-translation" in _classes(n))),
            "",
        )
        if sentence:
            examples.append(Example(sentence, rendering or None))
    return examples


def _senses_of(items: list) -> list[Sense]:
    """One sense per list item, with a nested list read as what it nests under.

    An item whose own text ends in a colon is a header and not a meaning --
    `inflection of auswandern:` -- so it is not a sense of its own and its text
    goes in front of each item nested under it.
    """
    senses = []
    for item in items:
        #: The colon is what marks a header, and `_tidy` strips it, so the
        #: test is made on the raw text: `inflection of curar:` is not a
        #: sense, it is what its sub-senses are inflections *of*.
        raw = _text(item, skip=("dl", "ol", "ul"))
        own = _tidy(raw)
        #: A sub-sense list is not always a direct child of the item that
        #: holds it -- it can sit inside the item's `dd` -- so it is looked
        #: for anywhere beneath, and its items are read one level flat.
        nested = [
            child
            for sublist in _find(item, lambda n: n.get("tag") == "ol")
            for child in sublist["children"]
            if not isinstance(child, str) and child.get("tag") == "li"
        ]
        header = raw.strip().endswith(":") or (nested and not own)
        if own and not header:
            senses.append(Sense(definition=own, examples=tuple(_html_examples(item))))
        for child in nested:
            inner = _tidy(_text(child, skip=("dl", "ol", "ul")))
            if not inner:
                continue
            senses.append(
                Sense(
                    definition=f"{own}: {inner}".strip() if header and own else inner,
                    examples=tuple(_html_examples(child)),
                )
            )
    return senses


def _entries_from_html(parse: dict | None, language: str) -> list[Entry]:
    """The language's entries, read from the rendered page.

    The walk follows document order rather than looking only at the top of the
    section: the section is sliced from its `<h2>`, which sits *inside* the
    heading's wrapper div, so the fragment is unbalanced and nesting depth
    means nothing. A list is a sense list when the nearest heading before it
    names a part of speech; a list inside a list item is a sub-sense and is
    left to the item that holds it.
    """
    if not isinstance(parse, dict):
        return []
    html = parse.get("parse", {}).get("text")
    if not isinstance(html, str):
        return []
    section = _language_section(html, language)
    if section is None:
        return []

    entries: list[Entry] = []
    state = {"heading": None}

    def walk(node, inside_item: bool) -> None:
        for child in node["children"]:
            if isinstance(child, str):
                continue
            tag = child.get("tag")
            if tag in ("h2", "h3", "h4", "h5", "h6"):
                state["heading"] = _tidy(_text(child, skip=("span",)))
                continue
            if tag == "ol" and not inside_item and state["heading"]:
                if (
                    state["heading"].casefold() not in _NOT_SENSES
                    and "references" not in _classes(child)
                ):
                    items = [
                        item
                        for item in child["children"]
                        if not isinstance(item, str) and item.get("tag") == "li"
                    ]
                    senses = _senses_of(items)
                    if senses:
                        entries.append(
                            Entry(
                                language=language,
                                part_of_speech=state["heading"],
                                senses=tuple(senses),
                            )
                        )
                    continue
            walk(child, inside_item or tag == "li")

    walk(_parse_tree(section), False)
    return entries


def _language_section(html: str, language: str) -> str | None:
    """The slice of the page between this language's heading and the next."""
    anchor = language.replace(" ", "_")
    headings = [(match.start(), match.group(1)) for match in _SECTION.finditer(html)]
    for position, (start, name) in enumerate(headings):
        if name != anchor:
            continue
        end = headings[position + 1][0] if position + 1 < len(headings) else len(html)
        return html[start:end]
    return None


def _etymology(section: str) -> str | None:
    """The first paragraph under the section's first Etymology heading."""
    heading = _ETYMOLOGY_HEADING.search(section)
    if heading is None:
        return None
    for paragraph in _PARAGRAPH.finditer(section, heading.end()):
        text = strip_html(paragraph.group(1))
        if text:
            return text
    return None


def audio_path(url: str, *, download: bool = True) -> Path | None:
    """Cache ``url``'s sound file next to the pages and return its path."""
    name = urllib.parse.unquote(url.rsplit("/", 1)[-1])
    path = cache_dir() / "audio" / re.sub(r"[^\w.\-]", "_", name)
    if path.exists():
        return path
    if not download:
        return None
    data = _fetch(url, what="audio")
    if not isinstance(data, bytes):
        return None
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path

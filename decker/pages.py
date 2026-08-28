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
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path

from decker.wiktionary import USER_AGENT, cache_dir

DEFINITION_URL = "https://{edition}.wiktionary.org/api/rest_v1/page/definition/{title}"
PARSE_URL = (
    "https://{edition}.wiktionary.org/w/api.php"
    "?action=parse&page={title}&prop=text&formatversion=2&format=json"
)

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
class Sense:
    """One numbered definition of a page, with the examples under it."""

    definition: str
    examples: tuple[str, ...] = ()


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
    audio_url: str | None = None

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


def page_cache_path(title: str, edition: str) -> Path:
    """Where a title's raw payloads are kept.

    Titles are quoted, so a title carrying a slash or a colon cannot escape
    the directory or collide with another.
    """
    safe = urllib.parse.quote(title, safe="")
    return cache_dir() / f"pages-{edition}" / f"{safe}.json.gz"


def fetch(title: str, *, edition: str, lang: str, refresh: bool = False) -> Page | None:
    """Return ``title``'s page as far as ``lang`` is concerned.

    ``None`` when the page does not exist, or exists without a section for
    the language -- an ordinary outcome, since a title may be spelled the
    same in a language the source text is not written in.
    """
    payloads = _payloads(title, edition=edition, refresh=refresh)
    if payloads is None:
        return None
    entries = _entries(payloads.get("definition"), lang)
    if not entries and _is_split(payloads):
        payloads, entries = _from_split(title, payloads, edition=edition, lang=lang, refresh=refresh)
    if not entries:
        return None
    etymology, ipa, audio = _from_html(payloads.get("parse"), entries[0].language)
    return Page(
        title=title,
        language=entries[0].language,
        entries=tuple(entries),
        etymology=etymology,
        ipa=ipa,
        audio_url=audio,
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
        entries = _entries(found.get("definition"), lang)
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
    definition = _get_json(DEFINITION_URL.format(edition=edition, title=quoted))
    if definition is None:
        return None
    parse = _get_json(PARSE_URL.format(edition=edition, title=quoted))
    payloads = {"definition": definition, "parse": parse}

    if _transient_failure(definition):
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


def _get_json(url: str) -> dict | list | None:
    """Fetch and decode one API response, waiting out throttling."""
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    for attempt in range(MAX_ATTEMPTS):
        _pace()
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            if error.code == 404:
                return None
            if error.code not in (429, 503) or attempt == MAX_ATTEMPTS - 1:
                print(f"[decker] {url}: HTTP {error.code}", file=sys.stderr)
                return None
            time.sleep(_retry_after(error, attempt))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
            if attempt == MAX_ATTEMPTS - 1:
                print(f"[decker] {url}: {error}", file=sys.stderr)
                return None
            time.sleep(BACKOFF**attempt)
    return None


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


def _entries(definition: dict | None, lang: str) -> list[Entry]:
    """Read the REST payload's entries for one language code."""
    if not isinstance(definition, dict):
        return []
    entries = []
    for block in definition.get(lang, ()):
        senses = tuple(
            Sense(
                definition=strip_html(sense.get("definition", "")),
                examples=tuple(_examples(sense)),
            )
            for sense in block.get("definitions", ())
            if strip_html(sense.get("definition", ""))
        )
        if senses:
            entries.append(
                Entry(
                    language=block.get("language", lang),
                    part_of_speech=block.get("partOfSpeech", ""),
                    senses=senses,
                )
            )
    return entries


def _examples(sense: dict) -> list[str]:
    """Examples of one sense, the translated ones rendered as a pair."""
    examples = []
    for parsed in sense.get("parsedExamples", ()):
        text = strip_html(parsed.get("example", ""))
        translation = strip_html(parsed.get("translation", ""))
        if text and translation:
            examples.append(f"{text} — {translation}")
        elif text:
            examples.append(text)
    if examples:
        return examples
    return [strip_html(example) for example in sense.get("examples", ()) if example]


def _from_html(
    parse: dict | None, language: str
) -> tuple[str | None, tuple[str, ...], str | None]:
    """Pull etymology, IPA and audio out of the rendered page."""
    if not isinstance(parse, dict):
        return None, (), None
    html = parse.get("parse", {}).get("text")
    if not isinstance(html, str):
        return None, (), None
    section = _language_section(html, language)
    if section is None:
        return None, (), None

    ipa = tuple(
        reading
        for raw in _IPA.findall(section)
        if (reading := strip_html(raw)).startswith(_IPA_DELIMITERS)
    )
    audio = _AUDIO.search(section)
    return (
        _etymology(section),
        ipa,
        f"https:{audio.group(1)}" if audio else None,
    )


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
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            data = response.read()
    except (urllib.error.URLError, TimeoutError) as error:
        print(f"[decker] {url}: {error}", file=sys.stderr)
        return None
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path

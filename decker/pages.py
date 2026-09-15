"""Wiktionary pages: fetching, caching, and the pieces a gloss is made of.

One endpoint is read per title, the parse endpoint, and everything a gloss is
made of is read out of the HTML it returns: the senses under each part of
speech, their examples, the etymology, the readings and the audio URLs. The
payload is cached verbatim, one gzipped file per title, so a page is fetched
once however many terms land on it, and which origin rendered it is cached
alongside -- a mirror serves the same paths and the same entries, but no
media. Audio is not part of that cache: the page keeps the URL, and the sound
file is downloaded next to it only when asked for.
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

from decker.languages import section_of
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
#: Any heading at all, used to stop an etymology running into what follows it.
_ANY_HEADING = re.compile(r"<h[1-6]\b")
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
    #: Glossary anchors this definition links to -- `first_person`,
    #: `singular_number`. Wiktionary links the linguistic terminology inside a
    #: definition to `Appendix:Glossary`, which is how the terminology is told
    #: from the words around it without a lexicon of decker's own.
    concepts: tuple[str, ...] = ()
    #: The titles this definition says its word is a form of, as Wiktionary's
    #: own markup names them: a form-of line wraps the word it points at in
    #: `form-of-definition-link`. Empty where the line is written by hand
    #: rather than through a template, and :func:`decker.glosses._targets`
    #: reads the prose instead.
    targets: tuple[str, ...] = ()


@dataclass(frozen=True)
class Concept:
    """One entry of `Appendix:Glossary`: a piece of terminology explained.

    Several anchors reach one entry -- `first_person`, `first-person` and
    `1st_person` are one concept with three spellings -- so the anchor a page
    happened to link is resolved to the entry, and the entry is what becomes a
    card. `name` is the entry's own first spelling, which is what the card is
    titled with, and `anchor` is where in the glossary it lives.
    """

    name: str
    description: str
    anchor: str


@dataclass(frozen=True)
class Entry:
    """One part of speech of one language on a page."""

    language: str
    part_of_speech: str
    senses: tuple[Sense, ...]
    #: The etymology of the block this part of speech sits under, where the
    #: section has more than one. Wiktionary nests a language as Etymology 1..N
    #: -> part of speech -> senses, and the senses under one etymology have
    #: nothing to do with the next: Spanish `mate` is from French in its first
    #: etymology and from Quechua in its third, and the drink belongs to the
    #: third. ``None`` where the section numbers no etymologies, and
    #: :attr:`Page.etymology` answers for the whole section as before.
    etymology: str | None = None
    #: Wiktionary's headword line for this part of speech, minus the headword
    #: itself: `f (plural servilletas)`. The gender and the paradigm, as the
    #: page announces them. Empty where the line carries nothing but the word.
    headword: str = ""


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
    #: The origin this page was rendered by, kept because a cached page
    #: outlives the run that fetched it and only some sources have audio.
    source: str = ""

    @property
    def senses(self) -> list[tuple[str, Sense]]:
        """Every sense of the page, each with the part of speech it sits under."""
        return [
            (entry.part_of_speech, sense)
            for entry in self.entries
            for sense in entry.senses
        ]

    def etymology_of(self, sense: Sense) -> str | None:
        """The etymology that belongs to this sense, not to the section.

        By identity rather than by value, the way sense pooling already
        matches them: one page can carry the same definition text under two
        etymologies, and those are two different words.

        The entry's own answer is the whole answer, ``None`` included. A
        numbered etymology is allowed to have no prose -- an inflected form
        has no origin of its own, it is the base word's -- and falling back to
        the section would hand it the first etymology on the page, which is
        the bug this exists to fix. :attr:`etymology` answers only for a sense
        this page does not hold.
        """
        for entry in self.entries:
            for one in entry.senses:
                if one is sense:
                    return entry.etymology
        return self.etymology

    def headword_of(self, sense: Sense) -> str:
        """The headword line of the part of speech this sense sits under."""
        for entry in self.entries:
            for one in entry.senses:
                if one is sense:
                    return entry.headword
        return ""


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


def carries_media(source: str) -> bool:
    """Whether pages from ``source`` can offer a recording at all.

    An audio URL is read off a rendered page, and only Wikimedia renders one:
    `File:` pages are in no dump, so a mirror's page is silent whatever the
    word. A cache entry written before the source was recorded can only have
    come from upstream, which is why an empty source counts as one.
    """
    return not source or source.endswith(".wiktionary.org")


def page_cache_path(title: str, edition: str) -> Path:
    """Where a title's raw payloads are kept.

    Keyed by title and edition alone, deliberately. A mirror and Wikimedia
    render the same entry from the same wikitext, so the definitions do not
    differ, and the one thing that does -- audio, which the mirror never has
    -- is a property of the payload rather than a reason to fetch the page
    twice. Two caches meant that pointing a run at a different source fetched
    every title again, which is exactly the stream of words a mirror exists to
    keep off the network. What the source decides is what a cached page can be
    trusted to say about audio; `carries_media` answers that.

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
    language = section_of(lang)
    entries = _entries_from_html(payloads.get("parse"), language)
    if not entries and _is_split(payloads):
        payloads, entries = _from_split(title, payloads, edition=edition, lang=lang, refresh=refresh)
    if not entries:
        pointed_at = _points_at(payloads, language, title)
        if pointed_at is not None:
            payloads, entries = _from_pointer(
                pointed_at, payloads, language, edition=edition, refresh=refresh
            )
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
        source=payloads.get("source", ""),
    )


#: A spelling whose entry lives under another spelling: Wiktionary writes one
#: as a box that points there, not as an entry of its own. The simplified 人类
#: heads a Chinese section whose whole content is "For pronunciation and
#: definitions of 人类 -- see 人類", and the sense reader, looking for a
#: numbered list, finds a page with nothing on it. Most of Chinese is written
#: this way: 82 % coverage in `docs/execution/language-survey.md` was a mixed-
#: script sample, and a wholly simplified text would lose most of itself.
#:
#: The box is a table whose class names the language's own see-template --
#: `zh-see` -- and the spelling it points at is the first link after the word
#: "see". Two regexes, as narrow as the form-of pair in `glosses.py` and for
#: the same reason: a page that merely *mentions* another is not this.
_SEE_BOX = re.compile(
    r'<table[^>]*\bclass="[^"]*\b[a-z]{2,4}-see\b[^"]*"[^>]*>(.*?)</table>',
    re.DOTALL,
)
_SEE_TARGET = re.compile(r'\bsee\b\s*(?:<[^>]+>\s*)*<a href="/wiki/([^"#]+)')


def _points_at(payloads: dict, language: str, title: str) -> str | None:
    """The spelling this page hands its section to, if it hands it anywhere.

    Read from inside the language section, so a box under another language --
    a page can be a variant spelling in one language and a word of its own in
    the next -- cannot answer for this one.
    """
    parse = payloads.get("parse")
    if not isinstance(parse, dict):
        return None
    html = parse.get("parse", {}).get("text")
    if not isinstance(html, str):
        return None
    section = _language_section(html, language)
    if section is None:
        return None
    box = _SEE_BOX.search(section)
    if box is None:
        return None
    pointed = _SEE_TARGET.search(box.group(1))
    if pointed is None:
        return None
    target = urllib.parse.unquote(pointed.group(1)).replace("_", " ")
    return target if target and target != title else None


def _from_pointer(
    target: str, payloads: dict, language: str, *, edition: str, refresh: bool
) -> tuple[dict, list]:
    """Read the section at the spelling this page points at.

    One hop, and the title stays the one the text used: 人类 is what the
    reader met and what the card teaches, and 人類 is only where the
    definitions are kept. The payloads travel with the entries, the way a
    split page's do, so the reading and the etymology come from the same
    place as the senses.
    """
    found = _payloads(target, edition=edition, refresh=refresh)
    if found is None:
        return payloads, []
    entries = _entries_from_html(found.get("parse"), language)
    return (found, entries) if entries else (payloads, [])


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
        entries = _entries_from_html(found.get("parse"), section_of(lang))
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
    #: The rendered page is the whole of it: senses, examples, etymology,
    #: readings and audio are all read out of this one payload, so it decides
    #: whether the title exists at all. A failed render is not written, so the
    #: next run has a chance at the page rather than a cached nothing.
    parse = _get_json(base + PARSE_PATH.format(title=quoted))
    if parse is None:
        return None
    #: Kept with the payload: a page is cached by title alone, so this is the
    #: only thing that later says whether its silence about audio is the word
    #: having no recording or the source having no media.
    payloads = {"parse": parse, "source": base}

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


#: Wiktionary's server-side failures that come back as page text under a 200,
#: and only those: a failure worth not caching is one that a second run might
#: not hit, which means a timeout and nothing else. Every other Scribunto
#: error is a fact about the wiki that answered -- `Lua error in
#: Module:zh-glyph`, which every Chinese page with a glyph box raises against
#: the mirror, and `Lua error: callParserFunction: function "#categoryTree"
#: was not found`, which every Hebrew prefix page raises there because the
#: mirror has no CategoryTree extension. Both will say the same thing
#: tomorrow, and neither touches the definitions. Matching them refused to
#: cache 狗, 雨, `ב־` and `מ־` at all, so the two languages this release
#: taught decker to read would have been re-fetched word by word on every run.
#: A page whose *definitions* really are error text yields no entries, and a
#: page with no entries was never going to be cached as a gloss anyway.
_TRANSIENT = (
    re.compile(r"the time allocated for running (?:lua modules|scripts) has expired"),
)


def _transient_failure(definition: object) -> bool:
    """Whether a definition payload is Wiktionary reporting its own failure."""
    text = json.dumps(definition, ensure_ascii=False).lower()
    return any(marker.search(text) for marker in _TRANSIENT)


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
    """Say how many fetches failed, and how many senses were error text."""
    if ERRORED_SENSES:
        total = sum(ERRORED_SENSES.values())
        kinds = ", ".join(f"{count} {kind}" for kind, count in sorted(ERRORED_SENSES.items()))
        print(
            f"[decker] {total} definitions were the wiki reporting a failure "
            f"({kinds}) and were left out; a mirror missing an extension is "
            "the usual reason -- see docs/execution/local-wiktionary.md",
            file=sys.stderr,
        )
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


#: Wiktionary renders its structure, and the REST definition endpoint decker
#: used to read flattened it, which is why the senses are read from the page
#: itself. A heading names a part of speech, the list under it holds one sense
#: per item, and an example arrives as its own elements -- `e-example` for the
#: sentence, `e-translation` for the rendering -- rather than as one string to
#: be cut apart. Sub-senses are nested where that payload made them siblings,
#: which is what once cost the lemma of an inflected form.
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


#: How Wiktionary links a piece of terminology to the glossary that explains
#: it. The fragment is the concept; the link text is whichever of the entry's
#: spellings the definition happens to use.
GLOSSARY_PAGE = "Appendix:Glossary"
_GLOSSARY_LINK = f"/wiki/{GLOSSARY_PAGE}#"

#: What Wiktionary wraps the word a form-of definition points at in. Its own
#: name for the relation decker otherwise has to infer from English prose.
_FORM_OF_LINK = "form-of-definition-link"

#: What Wiktionary wraps the line announcing a part of speech in: the word,
#: its gender, and the forms of its paradigm, each of them a link.
_HEADWORD_LINE = "headword-line"
#: The word itself inside that line, which the card already shows beside it.
_HEADWORD = "headword"


def _headword_of(line) -> str:
    """A headword line with the headword taken off the front.

    `servilleta f (plural servilletas)` becomes `f (plural servilletas)`: the
    gender and the paradigm, which is what the line adds, without the word,
    which the card is already showing. A line that is nothing but the word --
    an inflected form announcing itself -- comes back empty.
    """
    whole = _tidy(_text(line))
    head = ""
    for node in _find(line, lambda n: _HEADWORD in _classes(n)):
        head = _tidy(_text(node))
        break
    if head and whole.startswith(head):
        whole = whole[len(head) :]
    return whole.strip(" \t\n")


def _form_of_targets(node, *, skip=()) -> tuple[str, ...]:
    """The titles a form-of definition points at, as its markup names them.

    Wiktionary wraps them in `form-of-definition-link`, so the relation is
    read rather than guessed at: the prose reader takes the token after the
    word "of" and truncates every multi-word lemma -- `bichitos de luz` came
    back pointing at `bichito` where the page says `bichito de luz` -- and it
    knows only the two dozen grammar words someone wrote down. Empty for a
    line written by hand, which is why the prose reader stays as the fallback.
    """
    found: list[str] = []

    def walk(child, inside: bool) -> None:
        if isinstance(child, str) or child.get("tag") in skip:
            return
        inside = inside or _FORM_OF_LINK in _classes(child)
        if inside and child.get("tag") == "a":
            href = child["attrs"].get("href") or ""
            if href.startswith("/wiki/"):
                title = urllib.parse.unquote(href[len("/wiki/") :].split("#", 1)[0])
                #: A URL spells a space as an underscore; a title has the space.
                title = title.replace("_", " ")
                if title and title not in found:
                    found.append(title)
        for grandchild in child["children"]:
            walk(grandchild, inside)

    for child in node["children"]:
        walk(child, False)
    return tuple(found)


def _concepts_in(node, *, skip=()) -> tuple[str, ...]:
    """The glossary anchors linked under a node, in order, without repeats.

    Read over the same subtree the definition's own text is read over, so a
    sense is only credited with the terminology it actually names: a nested
    sub-sense has its own, and the example under a sense has none that belong
    to it.
    """
    found: list[str] = []

    def walk(child) -> None:
        if isinstance(child, str) or child.get("tag") in skip:
            return
        href = child["attrs"].get("href") or "" if child.get("tag") == "a" else ""
        if _GLOSSARY_LINK in href:
            anchor = urllib.parse.unquote(href.split("#", 1)[1])
            if anchor not in found:
                found.append(anchor)
        for grandchild in child["children"]:
            walk(grandchild)

    for child in node["children"]:
        walk(child)
    return tuple(found)


#: A definition that is the wiki reporting its own failure rather than a
#: meaning. It happens where a module a template calls is missing or broken --
#: an extension not loaded, an API the wiki's Scribunto predates -- and the
#: rendered page carries the message in the place the definition should be.
#: Two of those were found on the mirror and fixed there
#: (`docs/execution/local-wiktionary.md`); this is the guard that does not
#: depend on having found them. A card whose definition reads "Lua error in
#: Module:foo at line 63" is worse than a missing card: it is silent, it is
#: studied, and nothing in the run says it happened.
_ERROR_DEFINITION = re.compile(r"\b(?:lua error|script error)\b", re.I)

#: How many senses were dropped for being that, so a run can say so.
ERRORED_SENSES: Counter[str] = Counter()


def _senses_of(items: list) -> list[Sense]:
    """One sense per list item, with a nested list read as what it nests under.

    An item whose own text ends in a colon is a header and not a meaning --
    `inflection of auswandern:` -- so it is not a sense of its own and its text
    goes in front of each item nested under it.

    A sense that is a Lua or script error is not a sense at all and is dropped
    here, counted rather than glossed.
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
        #: Over the same subtree `raw` was read over, so the terminology a
        #: sense is credited with is the terminology its own definition names.
        own_concepts = _concepts_in(item, skip=("dl", "ol", "ul"))
        own_targets = _form_of_targets(item, skip=("dl", "ol", "ul"))
        if own and _ERROR_DEFINITION.search(own):
            #: Before the header test: an error can land anywhere a definition
            #: can, and one that happens to end in a colon is not a header
            #: with sub-senses, it is an error.
            ERRORED_SENSES[_ERROR_DEFINITION.search(own).group(0).lower()] += 1
            continue
        if own and not header:
            senses.append(
                Sense(
                    definition=own,
                    examples=tuple(_html_examples(item)),
                    concepts=own_concepts,
                    targets=own_targets,
                )
            )
        for child in nested:
            inner = _tidy(_text(child, skip=("dl", "ol", "ul")))
            if not inner:
                continue
            inner_concepts = _concepts_in(child, skip=("dl", "ol", "ul"))
            inner_targets = _form_of_targets(child, skip=("dl", "ol", "ul"))
            senses.append(
                Sense(
                    definition=f"{own}: {inner}".strip() if header and own else inner,
                    examples=tuple(_html_examples(child)),
                    #: A header's text is prefixed to its children, so its
                    #: terminology is theirs too -- `inflection of curar:`
                    #: carries the word, the lines under it carry the tags.
                    concepts=_merge(own_concepts if header else (), inner_concepts),
                    #: And so is the word it names: `inflection of curar:` is
                    #: where the link sits, and the lines under it are the
                    #: inflections *of* it.
                    targets=_merge(own_targets if header else (), inner_targets),
                )
            )
    return senses


def _merge(*groups: tuple[str, ...]) -> tuple[str, ...]:
    """Several anchor lists as one, in order, without repeats."""
    found: list[str] = []
    for group in groups:
        for anchor in group:
            if anchor not in found:
                found.append(anchor)
    return tuple(found)


def _entries_from_html(parse: dict | None, language: str) -> list[Entry]:
    """The language's entries, read from the rendered page.

    One etymology block at a time, so each part of speech keeps the etymology
    the page hangs it under rather than the section's first.
    """
    if not isinstance(parse, dict):
        return []
    html = parse.get("parse", {}).get("text")
    if not isinstance(html, str):
        return []
    section = _language_section(html, language)
    if section is None:
        return []
    return [
        entry
        for etymology, block in _etymology_blocks(section)
        for entry in _entries_in(block, language, etymology)
    ]


def _etymology_blocks(section: str) -> list[tuple[str | None, str]]:
    """The section cut at its Etymology headings, each block with its own text.

    Wiktionary numbers the etymologies of a language and hangs the parts of
    speech under whichever one they belong to. Reading the section whole gives
    every sense the first etymology, which is wrong on every page that has
    more than one -- Spanish `mate` has six, and the card for the drink said
    it came from French. Cutting first and walking each piece keeps the
    association the page already states.

    A section that numbers nothing is one block with no etymology of its own;
    :attr:`Page.etymology` answers for it, exactly as before.
    """
    headings = list(_ETYMOLOGY_HEADING.finditer(section))
    if not headings:
        #: Nothing numbered: one block, and whatever the section says once.
        return [(_etymology(section), section)]
    blocks: list[tuple[str | None, str]] = []
    #: Whatever precedes the first Etymology heading -- a Pronunciation the
    #: whole section shares, usually -- belongs to no etymology in particular.
    if headings[0].start() > 0:
        blocks.append((None, section[: headings[0].start()]))
    for position, heading in enumerate(headings):
        end = (
            headings[position + 1].start()
            if position + 1 < len(headings)
            else len(section)
        )
        block = section[heading.start() : end]
        blocks.append((_etymology(block), block))
    return blocks


def _entries_in(section: str, language: str, etymology: str | None) -> list[Entry]:
    """The parts of speech of one slice of a language section.

    The walk follows document order rather than looking only at the top of the
    slice: the slice is cut at an `<h2>` or an `<h3>`, which sits *inside* the
    heading's wrapper div, so the fragment is unbalanced and nesting depth
    means nothing. A list is a sense list when the nearest heading before it
    names a part of speech; a list inside a list item is a sub-sense and is
    left to the item that holds it.
    """
    entries: list[Entry] = []
    state = {"heading": None, "headword": ""}

    def walk(node, inside_item: bool) -> None:
        for child in node["children"]:
            if isinstance(child, str):
                continue
            tag = child.get("tag")
            if tag in ("h2", "h3", "h4", "h5", "h6"):
                state["heading"] = _tidy(_text(child, skip=("span",)))
                #: A part of speech announces itself or it does not; the one
                #: before it must not answer for it.
                state["headword"] = ""
                continue
            if _HEADWORD_LINE in _classes(child):
                state["headword"] = _headword_of(child)
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
                                etymology=etymology,
                                headword=state["headword"],
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
    """The first paragraph under the section's first Etymology heading.

    Bounded by the next heading of any level, because a numbered etymology is
    allowed to have no prose at all: `carga`'s second is a bare heading
    followed straight by its Verb, and an unbounded search walked past it and
    came back with the headword line -- "Deverbal from cargar." for the noun
    and "carga" for the verb form.
    """
    heading = _ETYMOLOGY_HEADING.search(section)
    if heading is None:
        return None
    following = _ANY_HEADING.search(section, heading.end())
    end = following.start() if following else len(section)
    for paragraph in _PARAGRAPH.finditer(section, heading.end(), end):
        text = strip_html(paragraph.group(1))
        if text:
            return text
    return None
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


def glossary(edition: str, *, refresh: bool = False) -> dict[str, Concept]:
    """Every concept `Appendix:Glossary` explains, by the anchors that reach it.

    The glossary is one long definition list: a `dt` naming a piece of
    terminology, carrying an invisible anchor for each spelling it answers to,
    and a `dd` explaining it. Several anchors therefore land on one entry --
    1,005 anchors over 595 entries in the English edition -- and returning the
    same :class:`Concept` for all of them is what keeps `first_person` and
    `1st_person` one card rather than two.

    One page, and one that is read from Wikimedia whatever `--wiktionary-host`
    says: see :func:`_glossary_page`.
    """
    payloads = _glossary_page(edition, refresh=refresh)
    if payloads is None:
        return {}
    html = (payloads.get("parse") or {}).get("parse", {}).get("text")
    if not isinstance(html, str):
        return {}

    concepts: dict[str, Concept] = {}
    for definition_list in _find(_parse_tree(html), lambda n: n.get("tag") == "dl"):
        anchors: list[tuple[str, str]] = []
        for child in definition_list["children"]:
            if isinstance(child, str):
                continue
            if child.get("tag") == "dt":
                anchors = _anchors_of(child)
                name = _heading_name(child) or (anchors[0][1] if anchors else "")
            elif child.get("tag") == "dd" and anchors:
                description = _tidy(_text(child))
                if description:
                    concept = Concept(
                        name=name, description=description, anchor=anchors[0][0]
                    )
                    for anchor, _ in anchors:
                        concepts.setdefault(anchor, concept)
                anchors = []
    return concepts


#: What a page's current revision is, asked for on its own because it is a
#: few hundred bytes where the glossary is half a megabyte.
REVISION_PATH = (
    "/w/api.php?action=query&prop=revisions&titles={title}"
    "&rvprop=ids&formatversion=2&format=json"
)


def _glossary_page(edition: str, *, refresh: bool = False) -> dict | None:
    """`Appendix:Glossary`, from the mirror when it has one, Wikimedia when not.

    It used to be Wikimedia unconditionally, because a mirror built from
    `pages-articles` appeared to have no `Appendix:` namespace, and pointing
    this at one would have turned concept identification off for exactly the
    runs a mirror is meant to serve. That turned out to be a property of how
    the mirror was built rather than of the dump: the pages were imported into
    the main namespace with their prefix as part of the title, because the
    namespace had not been declared yet. Declared, and with MediaWiki's own
    `namespaceDupes.php` run over them, the local `Appendix:Glossary` renders
    all 622 entries -- see `docs/execution/local-wiktionary.md`.

    So the mirror is asked first and Wikimedia is the fallback, which keeps the
    guarantee that made this an exception (a run never silently loses its
    concepts) and adds the one thing the exception cost: a run with no network
    at all now has them. A mirror's copy is a dump's copy, so it is cached
    without a revision and never re-asked.

    From Wikimedia, the page is live, and read once and then only when it
    changes: a cache with no way to notice would hold a stale copy for good,
    and re-fetching half a megabyte every run to find out would be worse. So
    the revision id is asked for -- a few hundred bytes -- and the page itself
    only when that id has moved. A run that cannot reach Wikimedia keeps the
    copy it has: a glossary one revision old explains `dative case` exactly as
    well.
    """
    upstream = DEFAULT_ORIGIN.format(edition=edition).rstrip("/")
    mirror = origin(edition)
    quoted = urllib.parse.quote(GLOSSARY_PAGE, safe="")
    path = page_cache_path(GLOSSARY_PAGE, edition)

    cached = None
    if path.exists() and not refresh:
        with gzip.open(path, "rt", encoding="utf-8") as stored:
            cached = json.load(stored)
        if cached.get("source") not in (upstream, mirror):
            #: Written against a source this run is not reading from.
            cached = None

    if mirror != upstream:
        if cached is not None and cached.get("source") == mirror:
            return cached
        parse = _get_json(mirror + PARSE_PATH.format(title=quoted))
        if _has_entries(parse):
            payloads = {"parse": parse, "source": mirror}
            _keep_glossary(path, payloads)
            return payloads
        print(
            f"[decker] {mirror} has no {GLOSSARY_PAGE}; reading it from "
            "Wikimedia instead, which is the one title a mirrored run still "
            "names upstream",
            file=sys.stderr,
        )

    revision = _revision(upstream, GLOSSARY_PAGE)
    if cached is not None and cached.get("source") == upstream and (
        revision is None or revision == cached.get("revision")
    ):
        return cached
    parse = _get_json(upstream + PARSE_PATH.format(title=quoted))
    if parse is None:
        #: Offline, or refused. What is already here beats nothing.
        return cached
    payloads = {"parse": parse, "source": upstream, "revision": revision}
    _keep_glossary(path, payloads)
    return payloads


def _has_entries(parse: object) -> bool:
    """Whether a parse payload carries a glossary rather than an API error.

    The definition list is the whole page, so one `<dt` is the test: a missing
    title comes back as an `error` object and a namespace that does not exist
    comes back as a page with no list in it.
    """
    if not isinstance(parse, dict):
        return False
    text = parse.get("parse", {}).get("text")
    return isinstance(text, str) and "<dt" in text


def _keep_glossary(path: Path, payloads: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as out:
        json.dump(payloads, out, ensure_ascii=False)


def _revision(origin: str, title: str) -> int | None:
    """The page's current revision id, or nothing if it cannot be asked for."""
    answer = _get_json(
        origin + REVISION_PATH.format(title=urllib.parse.quote(title, safe="")),
        quiet=True,
    )
    if not isinstance(answer, dict):
        return None
    for page in answer.get("query", {}).get("pages", []) or []:
        for revision in page.get("revisions", []) or []:
            if isinstance(revision.get("revid"), int):
                return revision["revid"]
    return None


#: Page furniture inside a glossary heading: the "English Wikipedia has an
#: article on" box sits inside the `dt` of a handful of entries, so the
#: heading's text has to be read past it.
_FURNITURE = "noprint"


def _heading_name(heading: dict) -> str:
    """What a glossary entry is called, out of the spellings it lists.

    A heading names its entry's spellings in one line, fullest first and
    abbreviations last -- "accusative case, acc.", "singular, singular number,
    sg., s" -- so the first of them is the one worth putting on a card. The
    anchors are ordered differently, and taking the first of *those* titled the
    accusative card `acc.`.
    """
    parts: list[str] = []

    def walk(node) -> None:
        if isinstance(node, str):
            parts.append(node)
            return
        if _FURNITURE in _classes(node):
            return
        for child in node["children"]:
            walk(child)

    walk(heading)
    return _tidy(re.sub(r"\s+", " ", "".join(parts)).split(",")[0])


def _anchors_of(heading: dict) -> list[tuple[str, str]]:
    """Every anchor a glossary heading answers to, each with its spelling.

    Wiktionary writes them as empty spans carrying the anchor as `id` and the
    readable form as `data-id` -- `id="first_person"`, `data-id="first person"`
    -- so an entry with no usable heading text still has a name to fall back
    on.
    """
    found = []
    for node in _find(heading, lambda n: "template-anchor" in _classes(n)):
        anchor = node["attrs"].get("id")
        if anchor:
            found.append((anchor, node["attrs"].get("data-id") or anchor.replace("_", " ")))
    return found

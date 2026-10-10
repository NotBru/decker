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
import http.client
import json
import os
import re
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, replace
from html import unescape
from html.parser import HTMLParser
from pathlib import Path

from decker.languages import lect_of, section_of
from decker.console import DETAIL, NORMAL, VERBOSE, count, log
from decker.reach import BLIPS, http_gate
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
_pacing = threading.Lock()

#: How many redirects one request follows before giving up. `urlopen` did this
#: for us and the connections below do not, so the number is written down:
#: enough for the one hop an upload URL takes, and not a loop.
MAX_REDIRECTS = 5

#: The kept-open connections, one per origin **per thread**. A connection is a
#: stream and two threads cannot share one, so the pool is thread-local; the
#: prefetcher and the gloss loop each keep their own and both are paced by the
#: same lock, which is what Wikimedia counts.
_pool = threading.local()

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
    #: from the words around it without a lexicon of decker's own. A link to a
    #: language's own appendix is here too, whole --
    #: `Appendix:Finnish verbal derivatives#Causative` -- which is how it is
    #: told from a bare glossary anchor: see :func:`concept_reference`.
    concepts: tuple[str, ...] = ()
    #: The titles this definition says its word is a form of, as Wiktionary's
    #: own markup names them: a form-of line wraps the word it points at in
    #: `form-of-definition-link`. Empty where the line is written by hand
    #: rather than through a template, and :func:`decker.glosses._targets`
    #: reads the prose instead.
    targets: tuple[str, ...] = ()
    #: The page's own word, where this definition quotes it: German `müssen`
    #: is defined *(auxiliary, with an infinitive -> “müssen” replaces the past
    #: participle) to have to...*. MediaWiki renders a link to the page's own
    #: title as `mw-selflink`, which is the wiki saying *this text is this
    #: entry's word* -- the one thing a substring match cannot tell, since a
    #: definition written in English is full of English words and one of them
    #: may be spelled like the word being defined. Read for
    #: :func:`decker.cards._unspelled`, which has to take the answer out of
    #: the question.
    quoted: tuple[str, ...] = ()


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
    #: The appendix the entry is on. `Appendix:Glossary` for nearly all of
    #: them; a language's own appendix for the terminology only it explains.
    page: str = "Appendix:Glossary"


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
    #: The terms of this same language that etymology decomposes the word
    #: into: `des-` and `cargar` for `descargar`, `veneno` and `-oso` for
    #: `venenoso`. A sum the page states, not a history -- the Latin an
    #: etymology walks back through is named here too and is not in this
    #: tuple, because a learner of Spanish is not owed a card for `carricare`.
    #: Per block for the same reason the etymology is: Spanish `para` is a
    #: preposition under one etymology and a clipping of `paramilitar` under
    #: another.
    etymons: tuple[str, ...] = ()
    #: Wiktionary's headword line for this part of speech, minus the headword
    #: itself: `f (plural servilletas)`. The gender and the paradigm, as the
    #: page announces them. Empty where the line carries nothing but the word.
    headword: str = ""
    #: The readings and recordings of *this block*, not of the section. A page
    #: that numbers its etymologies gives each one its own Pronunciation, and
    #: they are different words: Russian `в` is the letter, the preposition and
    #: an abbreviation of `вольт`, and pooling them put the letter's phoneme
    #: inventory and `[volʲt]` on the preposition's card. Empty where the block
    #: has no pronunciation of its own, and :class:`Page` answers instead.
    ipa: tuple[str, ...] = ()
    audio_urls: tuple[str, ...] = ()
    #: The *Readings* list of a block that documents a character: `Kan-on:
    #: けつ (ketsu)`, `Kun: きまる (kimaru, 決まる)`, one string per line the
    #: page writes. It is what a Japanese entry gives a kanji instead of a
    #: pronunciation, because a kanji has none of its own -- see
    #: :data:`decker.script._MANY_READINGS` -- and it is the thing a reader
    #: has to learn about the character. Only on the parts of speech that are
    #: about a character, :data:`_CHARACTER_PARTS`: the list belongs to the
    #: shape and not to a word that happens to share the block.
    readings: tuple[str, ...] = ()


@dataclass(frozen=True)
class Page:
    """A Wiktionary page, cut down to one language."""

    title: str
    language: str
    entries: tuple[Entry, ...] = ()
    etymology: str | None = None
    #: The section's own components, by the same rule, for a sense this page
    #: does not hold. :attr:`Entry.etymons` is what answers for one it does.
    etymons: tuple[str, ...] = ()
    ipa: tuple[str, ...] = ()
    #: Every recording the language section offers, in the order it lists
    #: them. A page can carry several -- `el` has one for Spain and one for
    #: Colombia -- and which of them a learner wants is not decker's to guess.
    audio_urls: tuple[str, ...] = ()
    #: The origin this page was rendered by, kept because a cached page
    #: outlives the run that fetched it and only some sources have audio.
    source: str = ""
    #: The section's character readings, from whichever block documents the
    #: character. Hoisted here for the same reason :attr:`ipa` is: a page
    #: numbers its etymologies below the `Kanji` block, so a sense read out
    #: of a numbered block would otherwise find none.
    readings: tuple[str, ...] = ()

    @property
    def senses(self) -> list[tuple[str, Sense]]:
        """Every sense of the page, each with the part of speech it sits under."""
        return [
            (entry.part_of_speech, sense)
            for entry in self.entries
            for sense in entry.senses
        ]

    @property
    def word_senses(self) -> list[tuple[str, Sense]]:
        """Every sense the page states about a *word* rather than a character.

        A Japanese page heads a `Kanji` block above its etymologies, and what
        that block glosses is the shape: 街 is *main street or boulevard*
        there, while the word a text actually uses it as is two blocks below
        -- the suffix -gai, *town, district, area*. Pooled into one numbered
        listing the character's gloss comes first, and it won: a manga deck
        taught *main street or boulevard* on a card fronted with a word, with
        the kanji's four readings under it and no pronunciation. The shape's
        gloss is a `Symbol:` card's answer, and :mod:`decker.glosses` reads it
        out of these same blocks for exactly that.

        Where a character block is all the page has, it stands: a kanji the
        language writes no word with alone still has to gloss as something,
        and what the page says about the shape beats no card at all.
        """
        words = [
            (entry.part_of_speech, sense)
            for entry in self.entries
            if entry.part_of_speech.strip().lower() not in _CHARACTER_PARTS
            for sense in entry.senses
        ]
        return words or self.senses

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

    def etymons_of(self, sense: Sense) -> tuple[str, ...]:
        """The terms this sense's own etymology decomposes the word into.

        By identity, and the entry's answer is the whole answer, exactly as
        :meth:`etymology_of`: an inflected form carries no etymology of its
        own, and handing it the first block's components would decompose a
        word it is not.

        The page's own title is never one of them. A word whose etymology
        names it -- an entry that lists its own spelling among a run -- would
        otherwise depend on itself.
        """
        for entry in self.entries:
            for one in entry.senses:
                if one is sense:
                    return tuple(t for t in entry.etymons if t != self.title)
        return tuple(t for t in self.etymons if t != self.title)

    def ipa_of(self, sense: Sense) -> tuple[str, ...]:
        """The readings of the block this sense sits under.

        The section's own where the block has none: a page with one
        pronunciation above its etymologies shares it, which is the ordinary
        case and the reason :attr:`ipa` still exists.
        """
        for entry in self.entries:
            for one in entry.senses:
                if one is sense:
                    return entry.ipa or self.ipa
        return self.ipa

    def audio_of(self, sense: Sense) -> tuple[str, ...]:
        """The recordings of the block this sense sits under, by the same rule."""
        for entry in self.entries:
            for one in entry.senses:
                if one is sense:
                    return entry.audio_urls or self.audio_urls
        return self.audio_urls

    def readings_of(self, sense: Sense) -> tuple[str, ...]:
        """The character readings of the block this sense sits under.

        The section's own where the block has none, exactly as :meth:`ipa_of`
        falls back: the `Kanji` block sits above `Etymology 1` and takes the
        readings with it, so the noun under a numbered block would otherwise
        find nothing where the page in fact says けつ.

        Empty on every page that documents a word rather than a character,
        which is what makes this safe to ask of any sense.
        """
        for entry in self.entries:
            for one in entry.senses:
                if one is sense:
                    return entry.readings or self.readings
        return self.readings

    def headword_of(self, sense: Sense) -> str:
        """The headword line of the part of speech this sense sits under."""
        for entry in self.entries:
            for one in entry.senses:
                if one is sense:
                    return entry.headword
        return ""


#: Elements whose contents are not text on the page. MediaWiki inlines a
#: template's stylesheet *inside the list item it styles* -- the definition of
#: 男の子 opens with a `<style>` holding
#: `.mw-parser-output .defdate{font-size:smaller}` -- and a reader that takes
#: every character it is handed puts that CSS on the card, in front of the
#: definition. Every Japanese entry carrying a date qualifier had it.
_UNREADABLE = frozenset(("style", "script"))


class _Stripper(HTMLParser):
    """Turn a fragment of Wiktionary's HTML into plain text."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._muted = 0

    def handle_starttag(self, tag, attrs) -> None:
        if tag in _UNREADABLE:
            self._muted += 1

    def handle_endtag(self, tag) -> None:
        if tag in _UNREADABLE and self._muted:
            self._muted -= 1

    def handle_data(self, data: str) -> None:
        if not self._muted:
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
    lect = lect_of(lang)
    entries = _entries_from_html(payloads.get("parse"), language, lect)
    if not entries and _is_split(payloads):
        payloads, entries = _from_split(title, payloads, edition=edition, lang=lang, refresh=refresh)
    if not entries:
        redirected = _redirects_to(payloads, title)
        if redirected is not None:
            payloads, entries, title = _from_redirect(
                redirected, payloads, title, language, edition=edition,
                refresh=refresh, lect=lect,
            )
    if not entries:
        pointed_at = _points_at(payloads, language, title)
        if pointed_at is not None:
            payloads, entries = _from_pointer(
                pointed_at, payloads, language, edition=edition, refresh=refresh, lect=lect
            )
    if not entries:
        return None
    language = entries[0].language or language
    etymology, etymons, ipa, audios, readings = _from_html(
        payloads.get("parse"), language, lect
    )
    return Page(
        title=title,
        language=language,
        entries=tuple(entries),
        etymology=etymology,
        etymons=etymons,
        ipa=ipa,
        audio_urls=audios,
        source=payloads.get("source", ""),
        readings=readings,
    )


#: A spelling whose entry lives under another spelling: Wiktionary writes one
#: as a box that points there, not as an entry of its own. The simplified 人类
#: heads a Chinese section whose whole content is "For pronunciation and
#: definitions of 人类 -- see 人類", and the sense reader, looking for a
#: numbered list, finds a page with nothing on it. Most of Chinese is written
#: this way: 82 % coverage in `docs/execution/language-survey.md` was a mixed-
#: script sample, and a wholly simplified text would lose most of itself.
#:
#: Japanese is written this way at least as heavily, and it cost a manga deck
#: 89 of its words on 2026-09-18 -- 飲む, 分かる, 出来る, ください, 無い --
#: every one of which has an entry, under the other spelling.
#:
#: The box is a table whose class names the language's own see-template --
#: `zh-see`, `ja-see` -- and the two editions word it differently, which is
#: why there are two target patterns and not one:
#:
#: * Chinese puts the spelling straight after the word: *see 人類*.
#: * Japanese names no spelling in the sentence -- *see the following entry*
#:   -- and sets the target below it in a 【 】 block, beside the definitions
#:   themselves.
#:
#: Narrow, as narrow as the form-of pair in `glosses.py` and for the same
#: reason: a page that merely *mentions* another is not this.
_SEE_OPENS = re.compile(r'<table[^>]*\bclass="[^"]*\b[a-z]{2,4}-see\b[^"]*"[^>]*>')
_SEE_TABLE = re.compile(r"</?table\b")
_SEE_TARGET = re.compile(r'\bsee\b\s*(?:<[^>]+>\s*)*<a href="/wiki/([^"#]+)')
#: The 【 】 block's own link. Japanese's box holds one per entry pointed at,
#: and a kana spelling can point at a great many -- いん at nineteen kanji
#: words, みる at both ミル and 見る. :func:`_points_at` follows the box only
#: when it names one, on Bru's call of 2026-09-18: the several are homophone
#: lists rather than spellings of one word, mostly reached from a fragment
#: Stanza cut rather than from a word the text used, and "the first of them"
#: is the answer decker refuses to give anywhere else.
_NAMESPACED = re.compile(r"^[A-Z][A-Za-z ]*:")
_SEE_ENTRY = re.compile(r'【\s*(?:<[^>]+>\s*)*<a href="/wiki/([^"#]+)')


def _see_box(section: str) -> str | None:
    """The see-box whole, nested tables and all.

    Written as a scan rather than as one more regex because the box *has* a
    table inside it -- the entries it points at are laid out in one -- and a
    non-greedy `(.*?)</table>` ends at that inner table's close, which is
    after the first entry and before every other. Reading a box for a single
    target that way answers `みる` with `ミル` and looks entirely correct
    while doing it.
    """
    opened = _SEE_OPENS.search(section)
    if opened is None:
        return None
    depth = 1
    for tag in _SEE_TABLE.finditer(section, opened.end()):
        depth += 1 if tag.group(0) == "<table" else -1
        if depth == 0:
            return section[opened.end():tag.start()]
    return section[opened.end():]


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
    box = _see_box(section)
    if box is None:
        return None
    #: A link into a namespace is never the spelling a box hands its
    #: definitions to: うぐいす's box also says where to *see* the category of
    #: kanji read that way, and that was taken for the target, so the 【鶯】
    #: entry below it was never read and the word went to a model, which
    #: called a bush warbler a swallow. Found 2026-10-10, once Sudachi stopped
    #: cutting the word in two.
    for named in _SEE_TARGET.finditer(box):
        target = _spelling(named.group(1), title)
        if target is not None and not _NAMESPACED.match(target):
            return target
    #: No spelling in the sentence, so the 【 】 blocks are the targets, and
    #: one of them is a pointer while several are a homophone list. `dict`
    #: rather than `set` because a box can name the same spelling twice and
    #: that is still one target.
    targets = {
        found: None
        for raw in _SEE_ENTRY.findall(box)
        if (found := _spelling(raw, title)) is not None
    }
    return next(iter(targets)) if len(targets) == 1 else None


def _spelling(href: str, title: str) -> str | None:
    """A `/wiki/` target as a title, or ``None`` if it is this page's own."""
    target = urllib.parse.unquote(href).replace("_", " ")
    return target if target and target != title else None


def _from_pointer(
    target: str,
    payloads: dict,
    language: str,
    *,
    edition: str,
    refresh: bool,
    lect: str = "",
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
    entries = _entries_from_html(found.get("parse"), language, lect)
    return (found, entries) if entries else (payloads, [])


#: A spelling the wiki keeps no page for at all: `греза` is a hard redirect to
#: `грёза`, the way every Russian word whose `ё` a text prints as `е` is, and
#: `East coast` to `East Coast`. The render of such a page is the redirect
#: notice and nothing else -- no language section, no senses -- so the word
#: reached the definer with nothing and was dropped, or, once there was a
#: stage for it, handed to a model that called `грез` a Polish word. Bru found
#: that one, 2026-09-16; 37 of the 8,870 pages in a warm cache are these, and
#: seven of them are the Russian `ё`.
#:
#: One regex, matching the list the notice is written as, which both parsers
#: emit: Parsoid marks the redirect with a `<link rel="mw:PageProp/redirect">`
#: as well, and the mirror's legacy parser does not.
#:
#: The target may name a section, `解決#Japanese`, which is how a Japanese
#: `-する` verb redirects to its noun; the fragment is dropped, the language
#: section being read by name anyway. Matching only a bare target missed
#: every one of them.
_REDIRECT = re.compile(r'class="redirectText">\s*<li>\s*<a href="/wiki/([^"#]+)(?:#[^"]*)?"')


def _redirects_to(payloads: dict, title: str) -> str | None:
    """The spelling this page is a hard redirect to, if it is one."""
    parse = payloads.get("parse")
    if not isinstance(parse, dict):
        return None
    html = parse.get("parse", {}).get("text")
    if not isinstance(html, str):
        return None
    found = _REDIRECT.search(html)
    if found is None:
        return None
    target = urllib.parse.unquote(found.group(1)).replace("_", " ")
    return target if target and target != title else None


def _from_redirect(
    target: str,
    payloads: dict,
    title: str,
    language: str,
    *,
    edition: str,
    refresh: bool,
    lect: str = "",
) -> tuple[dict, list, str]:
    """Read the page this one redirects to, and take its title with it.

    One hop -- a wiki does not follow a double redirect either -- and unlike
    the see-box above, **the title changes**. A see-box is a real section at a
    real spelling that keeps its definitions elsewhere, so the card stays
    fronted with the spelling the text used. A redirect is the dictionary
    saying this spelling is not an entry, and for the `ё` that is the whole
    point: `грёза` is the word, and the diaeresis the text dropped is where
    the stress falls. A card fronted `греза` would teach the spelling the
    reader could already read.
    """
    found = _payloads(target, edition=edition, refresh=refresh)
    if found is None:
        return payloads, [], title
    entries = _entries_from_html(found.get("parse"), language, lect)
    return (found, entries, target) if entries else (payloads, [], title)


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
        entries = _entries_from_html(found.get("parse"), section_of(lang), lect_of(lang))
        if entries:
            return found, entries
    return payloads, []


def _payloads(title: str, *, edition: str, refresh: bool) -> dict | None:
    """The two raw responses for a title, from cache or from the network."""
    path = page_cache_path(title, edition)
    if path.exists() and not refresh:
        with gzip.open(path, "rt", encoding="utf-8") as cached:
            count("page.cached")
            return json.load(cached)

    quoted = urllib.parse.quote(title, safe="")
    base = origin(edition)
    #: The rendered page is the whole of it: senses, examples, etymology,
    #: readings and audio are all read out of this one payload, so it decides
    #: whether the title exists at all. A failed render is not written, so the
    #: next run has a chance at the page rather than a cached nothing.
    count("page.fetched")
    parse = _get_json(base + PARSE_PATH.format(title=quoted))
    if parse is None:
        count("page.failed")
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
        log(
            f"[decker] {title!r} came back as a Wiktionary error page; "
            "using it once, not caching it",
            level=VERBOSE, kind="warn",
        )
        return payloads

    path.parent.mkdir(parents=True, exist_ok=True)
    #: Written beside and moved into place, the way an answer is: the page
    #: ahead of the gloss loop is fetched by another thread now, so a reader
    #: can arrive while a writer is halfway through, and two threads can want
    #: the same title at once. `os.replace` is atomic, and the name carries
    #: the writer so the two do not share a half-written file either.
    temporary = path.with_suffix(f".{os.getpid()}.{threading.get_ident()}.part")
    try:
        with gzip.open(temporary, "wt", encoding="utf-8") as out:
            json.dump(payloads, out, ensure_ascii=False)
        os.replace(temporary, path)
    except OSError:
        temporary.unlink(missing_ok=True)
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
        log(
            f"[decker] {total} definitions were the wiki reporting a failure "
            f"({kinds}) and were left out; a mirror missing an extension is "
            "the usual reason -- see docs/execution/local-wiktionary.md",
            kind="warn",
        )
    if not FAILURES:
        return
    parts = ", ".join(f"{count} {kind}" for kind, count in sorted(FAILURES.items()))
    log(f"[decker] {sum(FAILURES.values())} fetches failed: {parts}", kind="warn")


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
    #: A server that cannot be reached, or answers 5xx to everything, is an
    #: outage and is waited out at its gate -- see `decker.reach` -- so no
    #: page is lost to one. What is still given up on is what the server says
    #: about *this* request: a 5xx the rest of the site does not share, a
    #: status that is not an error of the moment, a body that is not JSON.
    attempt = 0
    blips = 0
    while True:
        _pace()
        try:
            body = _request(url)
            return body if decode is None else decode(body)
        except urllib.error.HTTPError as error:
            if error.code == 404:
                return None
            if error.code == 403:
                raise Refused(url) from error
            if error.code == 429:
                #: Throttled: the server is there and has said when to come
                #: back, so this is waited out however many times it takes.
                count("fetch.throttled")
                log(f"[decker] {url}: HTTP 429, waiting as asked",
                    level=VERBOSE, kind="warn")
                time.sleep(_retry_after(error, min(attempt, MAX_ATTEMPTS)))
                attempt += 1
                continue
            if error.code >= 500:
                if attempt < MAX_ATTEMPTS - 1:
                    time.sleep(_retry_after(error, attempt))
                    attempt += 1
                    continue
                if http_gate(url, USER_AGENT).wait(f"HTTP {error.code}"):
                    attempt = 0
                    continue
            if not quiet:
                log(f"[decker] {url}: HTTP {error.code}",
                    level=VERBOSE, kind="warn")
                FAILURES[f"{what}: HTTP {error.code}"] += 1
            return None
        except (urllib.error.URLError, TimeoutError) as error:
            if http_gate(url, USER_AGENT).wait(str(getattr(error, "reason", error))):
                continue
            blips += 1
            if blips < BLIPS:
                time.sleep(BACKOFF**blips)
                continue
            if not quiet:
                log(f"[decker] {url}: {error}", level=VERBOSE, kind="warn")
                FAILURES[f"{what}: unreachable"] += 1
            return None
        except json.JSONDecodeError as error:
            if attempt == MAX_ATTEMPTS - 1:
                if not quiet:
                    log(f"[decker] {url}: {error}", level=VERBOSE, kind="warn")
                    FAILURES[f"{what}: not JSON"] += 1
                return None
            time.sleep(BACKOFF**attempt)
            attempt += 1


def _get_json(url: str, *, quiet: bool = False) -> dict | list | None:
    """Fetch and decode one API response, waiting out throttling."""
    answer = _fetch(
        url, what="page", quiet=quiet, decode=lambda body: json.loads(body.decode("utf-8"))
    )
    return answer if isinstance(answer, (dict, list)) else None


def _connection(scheme: str, host: str) -> http.client.HTTPConnection:
    """This thread's open connection to an origin, opening one if there is none.

    One connection per origin, kept and reused. `urlopen` builds a fresh one
    for every call, and on a cold run that is DNS, TCP and a TLS handshake per
    page: **186 s of a 1,926 s run**, 9.7 %, measured in the profile of
    2026-09-21 (getaddrinfo 33.7 s, create_connection 88.3 s, do_handshake
    63.8 s over 968 requests). Nothing about what is fetched changes.

    Thread-local, because a connection carries one request at a time.
    """
    pool = getattr(_pool, "connections", None)
    if pool is None:
        pool = _pool.connections = {}
    key = (scheme, host)
    if key not in pool:
        opener = (
            http.client.HTTPSConnection if scheme == "https"
            else http.client.HTTPConnection
        )
        pool[key] = opener(host, timeout=30)
    return pool[key]


def _drop(scheme: str, host: str) -> None:
    """Forget this thread's connection to an origin, closing it if it is open.

    A kept connection is closed by the other end sooner or later -- a server's
    keep-alive timeout, a proxy, a sleep -- and the failure arrives as the
    *next* request on it. So a dead connection is dropped and the request is
    made again on a fresh one, which is what `urlopen` gave for free by never
    keeping one.
    """
    pool = getattr(_pool, "connections", None)
    if pool is None:
        return
    connection = pool.pop((scheme, host), None)
    if connection is not None:
        try:
            connection.close()
        except OSError:
            pass


def _request(url: str, redirects: int = MAX_REDIRECTS) -> bytes:
    """One GET on a kept connection, following a redirect and retrying a stale one.

    Raises what `urlopen` raised, since the caller decides what a 404, a 403
    and a 429 mean: `urllib.error.HTTPError` for a status the server sent, and
    `urllib.error.URLError` for a connection that could not be made at all.
    """
    parts = urllib.parse.urlsplit(url)
    path = urllib.parse.urlunsplit(("", "", parts.path or "/", parts.query, ""))
    headers = {"User-Agent": USER_AGENT, "Accept-Encoding": "identity"}
    for stale in (True, False):
        connection = _connection(parts.scheme, parts.netloc)
        try:
            connection.request("GET", path, headers=headers)
            response = connection.getresponse()
            body = response.read()
        except (http.client.HTTPException, ConnectionError, TimeoutError) as error:
            #: A connection that had been sitting idle is the ordinary reason,
            #: and it is not a failure of the request: drop it and ask again
            #: on a new one. Twice is enough -- a second failure is the
            #: network, not the pool.
            _drop(parts.scheme, parts.netloc)
            if stale:
                continue
            raise urllib.error.URLError(error) from error
        except OSError as error:
            _drop(parts.scheme, parts.netloc)
            if stale:
                continue
            raise urllib.error.URLError(error) from error
        if response.status in (301, 302, 303, 307, 308):
            where = response.getheader("Location")
            if where and redirects:
                return _request(urllib.parse.urljoin(url, where), redirects - 1)
        if response.status >= 400:
            raise urllib.error.HTTPError(
                url, response.status, response.reason, response.headers, None
            )
        return body
    raise urllib.error.URLError("unreachable")


def _pace() -> None:
    """Keep a floor between one request and the next, whoever is asking."""
    global _last_request
    with _pacing:
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
    parse: dict | None, language: str, lect: str = ""
) -> tuple[
    str | None, tuple[str, ...], tuple[str, ...], tuple[str, ...], tuple[str, ...]
]:
    """Pull etymology, its components, IPA, recordings and readings out of it.

    The etymology is the section's; the readings and the recordings are the
    *lect's* where the entry has lects and the caller named one. The character
    readings are the section's and are read here rather than off the entries
    because the block that carries them need not have produced one: 下 and 超
    head a `Kanji` block that is readings and no numbered definition, so there
    is no entry to hang them on and the page would answer nothing.
    """
    if not isinstance(parse, dict):
        return None, (), (), (), ()
    html = parse.get("parse", {}).get("text")
    if not isinstance(html, str):
        return None, (), (), (), ()
    section = _language_section(html, language)
    if section is None:
        return None, (), (), (), ()

    spoken = _spoken(_shared(section), lect)
    return (
        _etymology(section),
        _etymons(section, language),
        _readings(spoken),
        _audios(spoken),
        _character_readings(section),
    )


#: The varieties the English Wiktionary gives a Chinese entry a pronunciation
#: block for, in the order it writes them. Matched as link text, which is how
#: `Module:zh-pron` names them.
_LECT_NAMES = (
    "Mandarin", "Cantonese", "Gan", "Hakka", "Jin", "Northern Min",
    "Eastern Min", "Puxian Min", "Southern Min", "Hokkien", "Teochew", "Wu",
    "Xiang", "Middle Chinese", "Old Chinese",
)


def _lect_block(section: str, lect: str) -> str:
    """The slices of ``section`` holding one variety's pronunciation.

    Every slice, not the first: Wikimedia names each lect *twice* -- once in
    the collapsed block that carries the recording and again in the expanded
    one that carries the reading -- so taking the first match gave 狗 its
    Mandarin recording and none of its four Mandarin readings. The mirror's
    render names each lect once, which is why that only showed up against the
    real site. Each slice runs to whichever variety is named next, and they are
    joined.

    A lect name can also appear in a definition -- `Wu` is a surname -- so
    slices that turn out to hold neither a reading nor a recording are not the
    pronunciation, and the section is used whole instead, which is what every
    language without lects does.
    """
    named = [
        (match.start(), match.group(1))
        for match in re.finditer(r">(" + "|".join(_LECT_NAMES) + r")<", section)
    ]
    starts = [start for start, _ in named]
    blocks = []
    for position, (start, name) in enumerate(named):
        if name != lect:
            continue
        end = starts[position + 1] if position + 1 < len(starts) else len(section)
        blocks.append(section[start:end])
    joined = "".join(blocks)
    if joined and (_IPA.search(joined) or _AUDIO.search(joined)):
        return joined
    return section


#: The heading a reading sits under. Everything else in a block that looks like
#: IPA is prose *about* pronunciation rather than the word's: Russian `я` says
#: in a usage note that "г in the genitive ending is pronounced as /v/", and
#: `/v/` became one of the pronoun's readings.
_PRONUNCIATION_HEADING = re.compile(r'<h[2-6] id="Pronunciation[^"]*"')


def _pronunciation(block: str, lect: str = "") -> str:
    """The slice of a block that is its Pronunciation section.

    From the heading to the next heading of any level. Nothing when the block
    has no such heading, which is how a caller knows to fall back rather than
    read the whole block and collect its usage notes.
    """
    found = _PRONUNCIATION_HEADING.search(block)
    if found is None:
        return ""
    following = _ANY_HEADING.search(block, found.end())
    slice_ = block[found.start() : following.start() if following else len(block)]
    return _lect_block(slice_, lect) if lect else slice_


def _shared(section: str) -> str:
    """The part of a section that belongs to no etymology in particular.

    Everything above the first `Etymology 1`, which is where a page that
    numbers its etymologies puts the pronunciation they all share. A section
    that numbers nothing has one etymology and shares all of it.

    Reading the whole section instead is what put `[volʲt]` -- the abbreviation
    of `вольт` -- on the Russian preposition `в`, whose three etymologies each
    carry their own Pronunciation and are three different words.
    """
    headings = list(_ETYMOLOGY_HEADING.finditer(section))
    return section[: headings[0].start()] if headings else section


def _spoken(block: str, lect: str = "") -> str:
    """The slice of a block to read a pronunciation out of.

    Its Pronunciation section, and failing that the block itself -- a page that
    writes IPA without a heading for it is still a page whose IPA is the word's.
    A reconstruction is not: `/*Cə.kˤroʔ/` is what 狗 is thought to have sounded
    like three thousand years ago, and the asterisk says so in every language
    that has one, which is why `_readings` drops it.
    """
    return _pronunciation(block, lect) or (_lect_block(block, lect) if lect else block)


def _readings(block: str) -> tuple[str, ...]:
    """Every reading in a slice, minus what is not one."""
    return tuple(
        reading
        for raw in _IPA.findall(block)
        if (reading := strip_html(raw)).startswith(_IPA_DELIMITERS)
        and "*" not in reading
    )


#: The heading a character's readings sit under. Japanese writes it for every
#: kanji, and the Ryukyuan languages the English Wiktionary documents the same
#: way write it too -- Okinawan, Miyako, Kunigami, Yonaguni, Yaeyama, Yoron,
#: Amami, Okinoerabu, Tokunoshima. Measured over the 10,889 pages this
#: machine had cached: 426 Japanese blocks carry one, 89 Ryukyuan blocks do,
#: and one Vietnamese block does. No other language needs anything here --
#: Korean hanja and Vietnamese Han tự state their reading in the headword
#: line, which a card already shows, and Chinese writes a Pronunciation
#: section, which :func:`_readings` already reads.
_READINGS_HEADING = re.compile(r'<h[2-6] id="Readings[^"]*"')

#: What a page calls the parts of speech that are about a character rather
#: than about a word. A Readings list is a fact about the shape, so it is
#: attached to these and to nothing else in the same block; and a definition
#: written under one of them is a fact about the shape too, which is what
#: :attr:`Page.word_senses` keeps out of a word's listing.
_CHARACTER_PARTS = frozenset(
    ("kanji", "hanzi", "hanja", "han character", "character", "letter", "syllable")
)

#: The historical forms a reading is written back through: `けち (kechi) ←
#: けち (keti, historical) ← くゑち (kweti, ancient)`. The modern reading is
#: what a learner is being taught; the chain behind it is philology, and on a
#: card it is three times the length of the answer.
_HISTORICAL = "\u2190"


def _character_readings(block: str) -> tuple[str, ...]:
    """The lines of a `Readings` list, one string apiece.

    `Go-on: けち (kechi)`, `Kan-on: けつ (ketsu, Jōyō)`, `Kun: きまる (kimaru,
    決まる, Jōyō), きめる (kimeru, 決める, Jōyō)`. The page's own wording, kept
    as the page has it: which class a reading belongs to is half of what the
    line teaches -- an on'yomi is what a kanji takes in a compound and a
    kun'yomi is what it takes alone -- and decker has nothing truer to say
    about it than the entry does.

    From the heading to the next heading of any level, which is the same cut
    :func:`_pronunciation` makes, and only the list items directly under it.
    """
    found = _READINGS_HEADING.search(block)
    if found is None:
        return ()
    following = _ANY_HEADING.search(block, found.end())
    slice_ = block[found.start() : following.start() if following else len(block)]
    tree = _parse_tree(slice_)
    lines = []
    for item in _find(tree, lambda node: node.get("tag") == "li"):
        line = _tidy(_text(item).split(_HISTORICAL)[0])
        if line:
            lines.append(line)
    return tuple(lines)


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
    """The text under a node, leaving out whole subtrees by tag.

    :data:`_UNREADABLE` is left out whatever the caller asks for: a
    stylesheet inlined into a definition is not part of the definition, and no
    caller has ever wanted it.
    """
    if isinstance(node, str):
        return node
    if node.get("tag") in skip or node.get("tag") in _UNREADABLE:
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

#: Where the rest of the terminology lives. A language explains its own
#: grammar in appendices of its own -- `-taa` is "Forms causative verbs",
#: and *causative verbs* links `Appendix:Finnish verbal derivatives#Causative`
#: -- and a definition links into them exactly as it links into the glossary.
_APPENDIX_LINK = "/wiki/Appendix:"

#: Appendices a definition links that are not terminology. The bibliography
#: is a footnote's source, not something to teach.
_NOT_TERMINOLOGY = ("Appendix:Bibliography/",)


def concept_reference(href: str) -> str | None:
    """What a link inside a definition names as a concept, if anything.

    A glossary entry is its bare anchor, as it always was; an entry of any
    other appendix is its page and anchor whole, `Appendix:Swahili noun
    classes#M-wa_class`, since the anchor alone does not say which page it is
    on. Only a link to a *place* on an appendix counts: one with no fragment
    is a whole page -- `Appendix:Cyrillic script` under every letter, the
    pronunciation key under every reading -- and a page is not a concept.
    """
    if _GLOSSARY_LINK in href:
        return urllib.parse.unquote(href.split("#", 1)[1])
    if not href.startswith(_APPENDIX_LINK):
        return None
    path, _, fragment = href[len("/wiki/"):].partition("#")
    if not fragment:
        return None
    title = urllib.parse.unquote(path).replace("_", " ")
    if title.startswith(_NOT_TERMINOLOGY):
        return None
    return f"{title}#{urllib.parse.unquote(fragment)}"


def appendix_of(reference: str) -> tuple[str, str]:
    """A concept reference as the page it is on and the anchor on it."""
    if reference.startswith("Appendix:") and "#" in reference:
        page, _, anchor = reference.partition("#")
        return page, anchor
    return GLOSSARY_PAGE, reference

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


#: MediaWiki's classes for a link whose target is the page it is already on.
#: A bare one is the page -- rendered either as `<a class="mw-selflink
#: selflink">` or, where the link is the whole of what it marks, as
#: `<strong class="selflink">`, so the class they share is the one to test.
#: The `-fragment` one carries the section it points into, which on a
#: Wiktionary page is a *language*. All of them are the wiki's own markup and
#: not a template's, so they are on every self-quotation a definition links,
#: however that definition was written.
_SELF_LINK = "selflink"
_SELF_LINK_SECTION = "mw-selflink-fragment"


def _quoted_in(node, language: str, *, skip=()) -> tuple[str, ...]:
    """The spellings of its own word that this definition quotes.

    A definition quoting the word it defines is the one thing that cannot be
    taken out of a production card's question by looking at the letters: the
    question is written in the mother tongue, and the answer may be spelled
    like one of the mother tongue's own words. German `in` is defined
    *in, into*; blanking the letters leaves `■, into`, which is the reason
    :func:`decker.cards._unspelled` masks nothing in a shared script.

    So the wiki is asked instead of the letters, and it answers exactly:

    - `<a class="mw-selflink selflink">müssen</a>`, `<strong class=
      "selflink">der</strong>` -- a link to this page, so this is the entry's
      own word, quoted inside its own definition.
    - `<a class="mw-selflink-fragment" href="#German">der</a>` -- a link to
      *this language's* section of this page. Also the entry's own word.
    - `<a class="mw-selflink-fragment" href="#English">nice</a>`, in the
      German entry of `nice` defined *good, nice* -- a link to the **English**
      section. That is the mother tongue's word that happens to be spelled
      like the German one, and it is the whole of what must not be masked.
    - plain text -- prose. The `in` of *in, into* is this.

    The text as the page shows it, so a quotation spelled differently from
    the title -- a capital opening a sentence, an inflected display text --
    comes back as it stands and the caller compares.
    """
    anchor = language.replace(" ", "_")
    found: list[str] = []

    def walk(child) -> None:
        if isinstance(child, str) or child.get("tag") in skip:
            return
        classes = _classes(child)
        if _SELF_LINK in classes or _SELF_LINK_SECTION in classes:
            fragment = (child["attrs"].get("href") or "").lstrip("#")
            #: A bare self-link names the page and so the section it is
            #: written in; a fragment names one section, and only this
            #: language's is this word.
            if not fragment or fragment == anchor:
                quoted = _tidy(_text(child))
                if quoted and quoted not in found:
                    found.append(quoted)
            return
        for grandchild in child["children"]:
            walk(grandchild)

    for child in node["children"]:
        walk(child)
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
        anchor = concept_reference(href)
        if anchor and anchor not in found:
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


def _senses_of(items: list, language: str) -> list[Sense]:
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
        own_quoted = _quoted_in(item, language, skip=("dl", "ol", "ul"))
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
                    quoted=own_quoted,
                )
            )
        for child in nested:
            inner = _tidy(_text(child, skip=("dl", "ol", "ul")))
            if not inner:
                continue
            inner_concepts = _concepts_in(child, skip=("dl", "ol", "ul"))
            inner_targets = _form_of_targets(child, skip=("dl", "ol", "ul"))
            inner_quoted = _quoted_in(child, language, skip=("dl", "ol", "ul"))
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
                    #: A header's text is prefixed to the line, so a word it
                    #: quotes is quoted in the definition the card shows.
                    quoted=_merge(own_quoted if header else (), inner_quoted),
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


def _entries_from_html(
    parse: dict | None, language: str, lect: str = ""
) -> list[Entry]:
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
    entries = []
    for etymology, etymons, block in _etymology_blocks(section, language):
        #: The block's own, not the section's. Empty above the first numbered
        #: etymology and on a block that carries no Pronunciation of its own,
        #: which is when :class:`Page` answers with the shared one instead.
        spoken = _pronunciation(block, lect)
        entries.extend(
            _entries_in(
                block,
                language,
                etymology,
                etymons,
                ipa=_readings(spoken),
                audio_urls=_audios(spoken),
                #: The block's, not the section's: a page numbering several
                #: etymologies writes the Readings list under the character's
                #: own block, and only that block's parts of speech are about
                #: the character.
                readings=_character_readings(block),
            )
        )
    return entries


def _etymology_blocks(
    section: str, language: str
) -> list[tuple[str | None, tuple[str, ...], str]]:
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
        return [(_etymology(section), _etymons(section, language), section)]
    blocks: list[tuple[str | None, tuple[str, ...], str]] = []
    #: Whatever precedes the first Etymology heading -- a Pronunciation the
    #: whole section shares, usually -- belongs to no etymology in particular.
    if headings[0].start() > 0:
        blocks.append((None, (), section[: headings[0].start()]))
    for position, heading in enumerate(headings):
        end = (
            headings[position + 1].start()
            if position + 1 < len(headings)
            else len(section)
        )
        block = section[heading.start() : end]
        blocks.append((_etymology(block), _etymons(block, language), block))
    return blocks


def _entries_in(
    section: str,
    language: str,
    etymology: str | None,
    etymons: tuple[str, ...] = (),
    *,
    ipa: tuple[str, ...] = (),
    audio_urls: tuple[str, ...] = (),
    readings: tuple[str, ...] = (),
) -> list[Entry]:
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
                    senses = _senses_of(items, language)
                    if senses:
                        entries.append(
                            Entry(
                                language=language,
                                part_of_speech=state["heading"],
                                senses=tuple(senses),
                                etymology=etymology,
                                etymons=etymons,
                                headword=state["headword"],
                                ipa=ipa,
                                audio_urls=audio_urls,
                                #: To the character's own part of speech and
                                #: to no other: `決`'s block heads a Kanji
                                #: and, further down the same page, words
                                #: written with it.
                                readings=(
                                    readings
                                    if state["heading"].casefold()
                                    in _CHARACTER_PARTS
                                    else ()
                                ),
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


def _etymology_paragraph(section: str) -> str | None:
    """The first paragraph under the section's first Etymology heading, as HTML.

    Bounded by the next heading of any level, because a numbered etymology is
    allowed to have no prose at all: `carga`'s second is a bare heading
    followed straight by its Verb, and an unbounded search walked past it and
    came back with the headword line -- "Deverbal from cargar." for the noun
    and "carga" for the verb form.

    The markup is kept because two things are read out of this one paragraph
    and they have to be the same paragraph: the prose the card shows, and the
    terms the word decomposes into. A component named in a paragraph the card
    does not show would be a card whose reason for existing is invisible.
    """
    heading = _ETYMOLOGY_HEADING.search(section)
    if heading is None:
        return None
    following = _ANY_HEADING.search(section, heading.end())
    end = following.start() if following else len(section)
    for paragraph in _PARAGRAPH.finditer(section, heading.end(), end):
        if strip_html(paragraph.group(1)):
            return paragraph.group(1)
    return None


def _etymology(section: str) -> str | None:
    """That paragraph as prose, which is what a card shows."""
    paragraph = _etymology_paragraph(section)
    return strip_html(paragraph) if paragraph is not None else None


#: A mention inside an etymology, and the language section it points into.
#: Every term an etymology template renders is a link carrying the section's
#: own anchor in its fragment -- `/wiki/cargar#Spanish`, `/wiki/carrus#Latin`
#: -- which is what tells a component of the language from the Latin it came
#: out of. The gloss inside a mention -- `largo (“long”)` -- links the English
#: word with no fragment at all, so demanding one keeps the glosses out of the
#: reading. Namespaced titles are excluded for the same reason: `Appendix:
#: Glossary#inherited` hangs off the word *Inherited* and
#: `Reconstruction:Proto-Slavic/*` is not a page anyone can be taught.
_ETYMON_LINK = re.compile(r'<a\s[^>]*href="/wiki/([^":#]+)#([^"]+)"[^>]*>')

#: What a decomposition is written with: mentions joined by a plus, which is
#: what `{{affix}}`, `{{compound}}`, `{{univerbation}}`, `{{blend}}` and the
#: `By surface analysis` line all render -- `des- +‎ cargar`, `veneno +‎ -oso`.
#: The plus is the whole test, and it is the reason a doublet, a cognate and a
#: `Compare` list are not components: they are same-language mentions too, and
#: only a decomposition puts a plus between them.
_JOINER = "+"


def _etymons(section: str, language: str) -> tuple[str, ...]:
    """The terms of ``language`` this etymology decomposes the word into.

    A sum, in other words, and only a sum: the mentions of one plus-joined run
    that point into this language's own section. Measured over the warm cache
    -- 560 Spanish etymologies, 3,764 Russian, 1,355 Japanese -- and written
    up in `docs/execution/etymological-components.md`.

    A run may be mixed: `mamma +‎ -fero` is Latin and Spanish, and only the
    Spanish half is something to teach. A run of one is not a sum at all, so
    `Doublet of volear` and `Compare Portuguese voar` name nothing here.
    """
    paragraph = _etymology_paragraph(section)
    if paragraph is None:
        return ()
    anchor = language.replace(" ", "_")
    runs: list[list[tuple[str, str]]] = []
    end = 0
    for match in _ETYMON_LINK.finditer(paragraph):
        member = (_entry_title(match.group(1)), match.group(2))
        if runs and _JOINER in strip_html(paragraph[end : match.start()]):
            runs[-1].append(member)
        else:
            runs.append([member])
        end = match.end()
    found: list[str] = []
    for run in runs:
        if len(run) < 2:
            continue
        for title, fragment in run:
            if fragment == anchor and title not in found:
                found.append(title)
    return tuple(found)


def _entry_title(path: str) -> str:
    """The entry a `/wiki/` path names.

    A page too long for one document is split by language, and an etymology
    links the split rather than the entry: `además` is `a/languages M to Z`
    +‎ `demás`. The card is for the word it names.
    """
    title = urllib.parse.unquote(path).replace("_", " ")
    head, _, rest = title.partition("/")
    return head if rest.startswith("languages ") else title


def audio_path(url: str, *, download: bool = True) -> Path | None:
    """Cache ``url``'s sound file next to the pages and return its path."""
    name = urllib.parse.unquote(url.rsplit("/", 1)[-1])
    path = cache_dir() / "audio" / re.sub(r"[^\w.\-]", "_", name)
    if path.exists():
        return path
    if not download:
        return None
    log(f"[decker]     downloading {name}", level=DETAIL, kind="detail")
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

    return _definition_list(_parse_tree(html))


def _definition_list(tree: dict, page: str = GLOSSARY_PAGE) -> dict[str, Concept]:
    """The `dt`/`dd` entries of a glossary-shaped page, by anchor."""
    concepts: dict[str, Concept] = {}
    for definition_list in _find(tree, lambda n: n.get("tag") == "dl"):
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
                        name=name, description=description, anchor=anchors[0][0],
                        page=page,
                    )
                    for anchor, _ in anchors:
                        concepts.setdefault(anchor, concept)
                anchors = []
    return concepts


def appendix(title: str, *, edition: str, refresh: bool = False) -> dict[str, Concept]:
    """Every entry a language's appendix explains, by the anchors that reach it.

    Fetched and cached like any entry, from whichever source pages come from:
    unlike `Appendix:Glossary`, which every run asks for, which of these a run
    needs says what language its text is in and what grammar it uses, so a
    mirrored run never names one to Wikimedia. A mirror without the page
    leaves the links unresolved, counted like a glossary anchor with no entry.

    These pages are not one shape. A glossary of a language's own is either
    the `dt`/`dd` list `Appendix:Glossary` is, or a bulleted list whose items
    open with an anchor -- `Appendix:Japanese glossary`, `Appendix:Chinese
    glossary` -- and an appendix that is prose is sections, linked by the
    heading's id: `#Causative`, `#M-wa_class`. All three are read, and an
    anchor found in two of them keeps the first.

    Each name carries the page's, `causative (Finnish verbal derivatives)`:
    the glossary has a `causative` too, the two say different things, and a
    learner shown both needs to see they are not the same card twice.
    """
    payloads = _payloads(title, edition=edition, refresh=refresh)
    html = ((payloads or {}).get("parse") or {}).get("parse", {}).get("text")
    if not isinstance(html, str):
        return {}
    tree = _parse_tree(html)
    found: dict[str, Concept] = {}
    for source in (_definition_list(tree, title), _anchored_items(tree, title),
                   _sections(tree, title)):
        for anchor, concept in source.items():
            found.setdefault(anchor, concept)
    where = title.removeprefix("Appendix:")
    return {
        anchor: replace(concept, name=f"{concept.name} ({where})")
        for anchor, concept in found.items()
    }


#: An en dash between an item's name and what it says: `Rendaku (連濁) –
#: voicing of an unvoiced initial consonant...`.
_NAMED = " – "


def _anchored_items(tree: dict, page: str) -> dict[str, Concept]:
    """List items that open with an anchor: one entry each."""
    found: dict[str, Concept] = {}
    for item in _find(tree, lambda n: n.get("tag") in ("li", "dd")):
        anchors = [
            node for node in item["children"]
            if not isinstance(node, str) and "template-anchor" in _classes(node)
        ]
        if not anchors:
            continue
        text = _tidy(_text(item, skip=("ul", "ol", "dl")))
        bold = next(iter(_find(item, lambda n: n.get("tag") == "b")), None)
        name = _tidy(_text(bold)) if bold else ""
        head, named, rest = text.partition(_NAMED)
        description = rest if named else text
        name = name or _tidy(head if named else "") or (
            anchors[0]["attrs"].get("data-id") or ""
        )
        if not name or not description:
            continue
        ids = [_anchor_id(node) for node in anchors if node["attrs"].get("id")]
        if not ids:
            continue
        concept = Concept(
            name=name, description=_tidy(description), anchor=ids[0], page=page,
        )
        for anchor in ids:
            found.setdefault(anchor, concept)
    return found


_HEADINGS = ("h2", "h3", "h4", "h5", "h6")


def _anchor_id(node: dict) -> str:
    """An element's id as a link to it spells it.

    Some templates escape the id twice, so the page reads
    `id="ren&amp;#039;yōkei"` where the link reads `#ren&#39;yōkei`, and one
    unescaping leaves `ren&#039;yōkei` against `ren'yōkei`. A second makes
    them the same, and an id with no entity in it is untouched by it.
    """
    return unescape(node["attrs"].get("id") or "")


def _sections(tree: dict, page: str) -> dict[str, Concept]:
    """Sections of prose, one entry each: the heading, and its paragraphs.

    Only the paragraphs, and only the ones before the next heading of any
    level. An appendix section goes on into example lists and inflection
    tables, which are the appendix's to show and too much for a card; what
    the section *says* the thing is sits in its opening prose. A section with
    no paragraph of its own -- `Causative types`, a heading over subsections
    -- has nothing to put on a card and is left out.
    """
    found: dict[str, Concept] = {}
    for parent in [tree, *_find(tree, lambda n: bool(n["children"]))]:
        heading: tuple[str, str] | None = None
        paragraphs: list[str] = []

        def close() -> None:
            if heading and paragraphs:
                anchor, name = heading
                found.setdefault(anchor, Concept(
                    name=name, description=" ".join(paragraphs),
                    anchor=anchor, page=page,
                ))

        for child in parent["children"]:
            if isinstance(child, str):
                continue
            inner = (
                child if child.get("tag") in _HEADINGS
                else next((n for n in child["children"] if not isinstance(n, str)
                           and n.get("tag") in _HEADINGS), None)
                if "mw-heading" in _classes(child) else None
            )
            if inner is not None:
                close()
                anchor = _anchor_id(inner)
                heading = (anchor, _tidy(_text(inner))) if anchor else None
                paragraphs = []
            elif heading and child.get("tag") == "p":
                if paragraph := _tidy(_text(child)):
                    paragraphs.append(paragraph)
        close()
    return found


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
    only when that id has moved. A run whose Wikimedia is down waits for it,
    as every fetch does (`decker.reach`); one that is refused keeps the copy
    it has, since a glossary one revision old explains `dative case` exactly
    as well. A mirror that does not answer is waited for too, and never read
    as a mirror without the page -- that would switch the run's source over a
    dropped connection.
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
        log(
            f"[decker] {mirror} has no {GLOSSARY_PAGE}; reading it from "
            "Wikimedia instead, which is the one title a mirrored run still "
            "names upstream",
            kind="warn",
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

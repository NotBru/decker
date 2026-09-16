"""The Wiktionary side of term extraction: page titles and their trees.

The title list is the whole ns0 dump of a Wiktionary edition. Titles of a
single word need no parse -- their tree is one node, so looking them up is a
set membership test against the spellings a source token answers to. Only
multi-word titles get parsed into pattern trees, and their parses are cached
on disk so the cost is paid once.
"""

from __future__ import annotations

import gzip
import importlib.metadata
import json
import os
import re
import sys
import urllib.request
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from pathlib import Path

import stanza

from decker import trees
from decker.console import VERBOSE, console, log
from decker.languages import joiner_of
from decker.nlp import pipeline
from decker.trees import Node

DUMP_URL = (
    "https://dumps.wikimedia.org/{edition}wiktionary/latest/"
    "{edition}wiktionary-latest-all-titles-in-ns0.gz"
)
def _user_agent() -> str:
    """Identify decker to Wikimedia, as its policy asks, from its own metadata."""
    metadata = importlib.metadata.metadata("decker")
    #: The homepage is the contact, named rather than taken by position: this
    #: URL is the only way Wikimedia has to reach a human before blocking the
    #: client, so which one it is should be a decision and not an artefact of
    #: the order the project's URLs happen to be written in. Any other URL
    #: stands in only if there is no homepage at all.
    urls = [
        (label.strip().casefold(), url.strip())
        for label, _, url in (
            entry.partition(",") for entry in metadata.get_all("Project-URL") or ()
        )
        if url
    ]
    contacts = [url for label, url in urls if label == "homepage"] + [
        url for label, url in urls if label != "homepage"
    ]
    contact = f"{contacts[0]}; " if contacts else ""
    return f"decker/{metadata['Version']} ({contact}{metadata['Summary']})"


USER_AGENT = _user_agent()

#: Titles are parsed in batches of this many, to keep Stanza's batching busy.
PARSE_CHUNK = 500

_WORD = re.compile(r"\w+", re.UNICODE)


@dataclass
class TitleIndex:
    """Wiktionary titles, ready to be matched against source sentences."""

    edition: str
    #: Titles of a single word, matched by spelling alone.
    words: set[str] = field(default_factory=set)
    #: Multi-word title trees, keyed by the spelling of their root token.
    phrases: dict[str, list[tuple[str, Node]]] = field(default_factory=dict)

    def add_phrase(self, title: str, tree: Node) -> None:
        for label in tree.labels:
            self.phrases.setdefault(label, []).append((title, tree))

    def phrases_rooted_at(self, labels: Iterable[str]) -> Iterator[tuple[str, Node]]:
        for label in labels:
            yield from self.phrases.get(label, ())


def cache_dir() -> Path:
    """Where dumps and parsed titles are kept between runs."""
    override = os.environ.get("DECKER_CACHE_DIR")
    if override:
        return Path(override)
    base = os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache"
    return Path(base) / "decker"


def dump_path(edition: str, *, refresh: bool = False) -> Path:
    """Return the local copy of the edition's title dump, downloading if needed."""
    path = cache_dir() / f"{edition}wiktionary-all-titles.gz"
    if path.exists() and not refresh:
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    url = DUMP_URL.format(edition=edition)
    log(f"[decker] downloading {url}", kind="head")
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    partial = path.with_suffix(".gz.part")
    with urllib.request.urlopen(request) as response, partial.open("wb") as out:
        #: Tens of megabytes over whatever connection the run has, once per
        #: edition, and the only stage that can honestly count bytes because
        #: the server says how many there are. Not skippable: half a dump is
        #: not a dump, and the run has nothing to do without it.
        size = int(response.headers.get("Content-Length") or 0)
        with console.phase("dump", size, skippable=False):
            while chunk := response.read(1 << 20):
                out.write(chunk)
                console.advance(len(chunk))
    partial.replace(path)
    log(f"[decker] {path.stat().st_size // (1 << 20)} MB of titles cached at "
        f"{path}", level=VERBOSE, kind="detail")
    return path


def iter_titles(path: Path) -> Iterator[str]:
    """Yield the page titles of a dump, with underscores turned back into spaces."""
    with gzip.open(path, "rt", encoding="utf-8") as dump:
        for line in dump:
            title = line.strip()
            if title:
                yield title.replace("_", " ")


def build_index(
    edition: str,
    *,
    lang: str,
    vocabulary: set[str] | None = None,
    refresh: bool = False,
) -> TitleIndex:
    """Build the title index for ``edition``.

    ``vocabulary`` is the set of lower-cased spellings the source text can
    offer. When given, only titles that could conceivably match are kept and
    parsed, which is what makes a run over one text cheap; pass ``None`` to
    build the whole index the design's one-time setup describes.
    """
    path = dump_path(edition, refresh=refresh)
    joiner = joiner_of(lang)
    index = TitleIndex(edition=edition)
    pending: list[str] = []
    #: Nine million titles off a gzipped dump, which is twenty seconds of
    #: nothing at all being printed. The bar counts compressed bytes -- the
    #: only total known before the read -- and the line says where they are
    #: coming from, since a run that is silently re-downloading the dump and a
    #: run that is reading a cached one look identical from outside.
    log(f"[decker] scanning {path.name} for titles this text could use",
        kind="head")
    read = 0
    with console.phase("index", path.stat().st_size, skippable=False):
        for read, title in enumerate(iter_titles(path), start=1):
            if " " in title:
                if vocabulary is None or _reachable(title, vocabulary):
                    pending.append(title)
            elif vocabulary is None or _spelled(title, joiner) in vocabulary:
                index.words.add(title)
            if read % _BAR_STEP == 0:
                console.advance(int(_BAR_STEP / _TITLES_PER_BYTE))
    log(f"[decker] {read} titles read", level=VERBOSE, kind="detail")
    log(
        f"[decker] {len(index.words)} single-word titles, "
        f"{len(pending)} multi-word titles to parse"
    )
    for title, tree in _parse_titles(pending, lang=lang, edition=edition):
        index.add_phrase(title, tree)
    return index


#: Titles per compressed byte, near enough for a bar: the dump is one short
#: line per title and gzip gets it to about a byte and a half. The bar is drawn
#: against the file's size on disk, so the share it shows is a few percent out
#: at worst -- which is all a bar is for, and cheaper than asking the
#: decompressor where it is every line.
_TITLES_PER_BYTE = 0.66
#: How often to redraw it. Every line would spend more time on the terminal
#: than on the titles.
_BAR_STEP = 50_000


def _spelled(title: str, joiner: str) -> str:
    """The title as a source text could spell it, for the vocabulary filter.

    A bound morpheme is written with a joiner the running text never has --
    Hebrew `ל־` against a text that only ever writes `ל` -- so a vocabulary
    built from the text would throw the title away before term extraction
    could ask for it. The joiner is only stripped for a language that has one,
    so nothing else grows an entry it did not have.
    """
    return (title.rstrip(joiner) if joiner else title).lower()


def _reachable(title: str, vocabulary: set[str]) -> bool:
    """Could every word of ``title`` be spelled by some token of the source?"""
    for part in title.split():
        lowered = part.lower()
        if lowered in vocabulary:
            continue
        chunks = _WORD.findall(lowered)
        if chunks and all(chunk in vocabulary for chunk in chunks):
            continue
        return False
    return True


def _parse_titles(
    titles: list[str], *, lang: str, edition: str
) -> Iterator[tuple[str, Node]]:
    """Parse multi-word titles into pattern trees, reusing the on-disk cache."""
    cache_path = cache_dir() / f"phrases-{edition}-{lang}.jsonl"
    cached = _load_parsed(cache_path)
    missing = [title for title in titles if title not in cached]
    if missing:
        log(f"[decker] parsing {len(missing)} titles", kind="head")
        nlp = pipeline(lang)
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        with cache_path.open("a", encoding="utf-8") as cache_file, console.phase(
            "titles", len(missing)
        ):
            for done, (title, tree) in enumerate(
                _parse_chunked(nlp, missing), start=1
            ):
                if console.skipping():
                    #: Every title parsed so far is already in the cache file,
                    #: so stopping costs the ones not reached and nothing else:
                    #: the index simply knows fewer phrases this run.
                    break
                cached[title] = tree
                cache_file.write(
                    json.dumps(
                        {"t": title, "d": trees.to_json(tree) if tree else None},
                        ensure_ascii=False,
                    )
                    + "\n"
                )
                console.advance()
                if done % 2000 == 0:
                    log(f"[decker] parsed {done}/{len(missing)}", level=VERBOSE,
                        kind="detail")

    for title in titles:
        tree = cached.get(title)
        if tree is not None:
            yield title, tree


def _parse_chunked(nlp, titles: list[str]) -> Iterator[tuple[str, Node | None]]:
    for start in range(0, len(titles), PARSE_CHUNK):
        chunk = titles[start : start + PARSE_CHUNK]
        docs = nlp.bulk_process([stanza.Document([], text=title) for title in chunk])
        for title, doc in zip(chunk, docs):
            tree = None
            if len(doc.sentences) == 1:
                tree = trees.title_tree(doc.sentences[0])
            yield title, tree


def _load_parsed(path: Path) -> dict[str, Node | None]:
    parsed: dict[str, Node | None] = {}
    if not path.exists():
        return parsed
    with path.open(encoding="utf-8") as cache_file:
        for line in cache_file:
            record = json.loads(line)
            data = record["d"]
            parsed[record["t"]] = trees.from_json(data) if data else None
    return parsed


def vocabulary_of(sentence_trees: Iterable[Node]) -> set[str]:
    """Every lower-cased spelling the source tokens can be looked up under."""
    vocabulary: set[str] = set()
    for tree in sentence_trees:
        for node in tree.walk():
            vocabulary.update(label.lower() for label in node.labels)
    return vocabulary

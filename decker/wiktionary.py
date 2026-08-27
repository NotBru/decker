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
from decker.nlp import pipeline
from decker.trees import Node

DUMP_URL = (
    "https://dumps.wikimedia.org/{edition}wiktionary/latest/"
    "{edition}wiktionary-latest-all-titles-in-ns0.gz"
)
def _user_agent() -> str:
    """Identify decker to Wikimedia, as its policy asks, from its own metadata."""
    metadata = importlib.metadata.metadata("decker")
    contacts = [
        url.split(",", 1)[1].strip()
        for url in metadata.get_all("Project-URL") or ()
        if "," in url
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
    print(f"[decker] downloading {url}", file=sys.stderr)
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    partial = path.with_suffix(".gz.part")
    with urllib.request.urlopen(request) as response, partial.open("wb") as out:
        while chunk := response.read(1 << 20):
            out.write(chunk)
    partial.replace(path)
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
    index = TitleIndex(edition=edition)
    pending: list[str] = []
    for title in iter_titles(path):
        if " " in title:
            if vocabulary is None or _reachable(title, vocabulary):
                pending.append(title)
        elif vocabulary is None or title.lower() in vocabulary:
            index.words.add(title)
    print(
        f"[decker] {len(index.words)} single-word titles, "
        f"{len(pending)} multi-word titles to parse",
        file=sys.stderr,
    )
    for title, tree in _parse_titles(pending, lang=lang, edition=edition):
        index.add_phrase(title, tree)
    return index


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
        print(f"[decker] parsing {len(missing)} titles", file=sys.stderr)
        nlp = pipeline(lang)
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        with cache_path.open("a", encoding="utf-8") as cache_file:
            for done, (title, tree) in enumerate(
                _parse_chunked(nlp, missing), start=1
            ):
                cached[title] = tree
                cache_file.write(
                    json.dumps(
                        {"t": title, "d": trees.to_json(tree) if tree else None},
                        ensure_ascii=False,
                    )
                    + "\n"
                )
                if done % 2000 == 0:
                    print(f"[decker] parsed {done}/{len(missing)}", file=sys.stderr)

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

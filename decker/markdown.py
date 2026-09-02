"""Glosses as a readable document, one heading each.

A heading here is a gloss, not the recognition/production pair deck
construction makes from it: this document is for reading the glosses a run
produced, which is easier done before they are cut into card faces.
Audio appears as Wiktionary's own link rather than the cached sound file: the
cache path is of no use to a reader of the document, and the link is there
whether or not the run downloaded anything.
"""

from __future__ import annotations

import posixpath
import re
import urllib.parse
from collections.abc import Iterable

from decker.glosses import Gloss

WIKTIONARY = "https://{edition}.wiktionary.org/wiki/{title}#{language}"
WIKTIONARY_HOME = "https://{edition}.wiktionary.org/"
LICENSE_URL = "https://creativecommons.org/licenses/by-sa/4.0/"

#: Definitions, examples and etymologies are Wiktionary's text, quoted whole.
#: It is CC BY-SA, which asks for the source to be named and the licence to
#: travel with it; each gloss already links to the entry it came from.
ATTRIBUTION = (
    "Definitions, examples, etymologies and pronunciations come from "
    "[Wiktionary]({home}), and are used under "
    "[CC BY-SA 4.0]({license}). Each gloss links to the entry it was taken from."
)


def render(
    glosses: Iterable[Gloss],
    *,
    title: str,
    edition: str = "en",
) -> str:
    """Render glosses as Markdown, one H2 apiece."""
    glosses = list(glosses)
    lines = [
        f"# {title}",
        "",
        f"{len(glosses)} glosses, in the order their terms occur — one per sense, so a "
        "word used in two meanings appears twice. Each heading is one gloss; deck "
        "construction turns each into a recognition card and a production card.",
        "",
    ]
    by_index = {gloss.index: gloss for gloss in glosses}
    for gloss in glosses:
        lines += _gloss(gloss, edition=edition, by_index=by_index)
    lines += _attribution(edition)
    return "\n".join(lines).rstrip() + "\n"


def _attribution(edition: str) -> list[str]:
    """Name Wiktionary and its licence, once, at the foot of the document."""
    return [
        "---",
        "",
        ATTRIBUTION.format(
            home=WIKTIONARY_HOME.format(edition=edition), license=LICENSE_URL
        ),
        "",
    ]


def _gloss(gloss: Gloss, *, edition: str, by_index: dict[int, Gloss]) -> list[str]:
    lines = [f"## {_heading(gloss)}", ""]

    facts = []
    if gloss.lemma != gloss.surface:
        facts.append(f"**lemma** {gloss.lemma}")
    facts.append(
        f"**entry** [{gloss.entry}]({entry_url(gloss.entry, edition, gloss.language)})"
    )
    if gloss.ipa:
        facts.append("**IPA** " + " ".join(f"`{reading}`" for reading in gloss.ipa))
    if gloss.audio_urls:
        facts.append(
            "**audio** "
            + " ".join(f"[{_file_name(url)}]({url})" for url in gloss.audio_urls)
        )
    lines += [" · ".join(facts), ""]

    if gloss.depends_on:
        after = ", ".join(
            _dependency(index, by_index) for index in gloss.depends_on
        )
        lines += [f"**Depends on** {after}", ""]

    lines += [gloss.definition, ""]

    if gloss.examples:
        for example in gloss.examples:
            lines.append(f"> {example}")
        lines.append("")

    if gloss.etymology:
        lines += [f"*{gloss.etymology}*", ""]
    return lines


def _heading(gloss: Gloss) -> str:
    return f"{gloss.index}. {gloss.surface}"


def _dependency(index: int, by_index: dict[int, Gloss]) -> str:
    """A link to the gloss this one is to be learned after."""
    dependency = by_index.get(index)
    if dependency is None:
        return str(index)
    heading = _heading(dependency)
    return f"[{heading}](#{_anchor(heading)})"


def _anchor(heading: str) -> str:
    """The heading's own anchor, spelled the way Markdown renderers derive it."""
    slug = re.sub(r"[^\w\- ]", "", heading.lower())
    return slug.replace(" ", "-")


def _file_name(url: str) -> str:
    """The sound file's name, as Wiktionary spells it."""
    return urllib.parse.unquote(posixpath.basename(url))


def entry_url(title: str, edition: str, language: str) -> str:
    """The Wiktionary URL of one entry, at its own language's section."""
    return WIKTIONARY.format(
        edition=edition,
        title=urllib.parse.quote(title.replace(" ", "_"), safe=""),
        language=language.replace(" ", "_"),
    )

"""Anki output: the shuffled cards as a deck on disk.

One note per card rather than one note with two templates, because the two
cards of a gloss are ordered separately -- shuffling can put a production card
a hundred cards after the recognition card it depends on, and Anki's new-card
order is a property of the note. Each note carries its position as its due
number, so the deck is studied in the order shuffling produced.

Anki ids are stable functions of the deck's name, so building the same deck
twice and importing both updates the notes instead of doubling them.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from pathlib import Path

import genanki

from decker.cards import PRODUCTION, RECOGNITION, Card, Side
from decker.markdown import LICENSE_URL, WIKTIONARY_HOME, entry_url

#: Wiktionary's text is CC BY-SA: the licence has to travel with the deck, and
#: a deck is read one card at a time, so every card carries the credit as well
#: as the deck carrying it once in its description.
CREDIT = (
    '<a href="{entry}">{title}</a> on Wiktionary, '
    '<a href="{license}">CC BY-SA 4.0</a>'
)

DESCRIPTION = (
    "Built by decker from {source}. Definitions, examples, etymologies and "
    'pronunciations come from <a href="{home}">Wiktionary</a>, used under '
    '<a href="{license}">CC BY-SA 4.0</a>; each card links to the entry it '
    "was taken from."
)

CSS = """\
.card {
  font-family: -apple-system, system-ui, sans-serif;
  font-size: 20px;
  text-align: center;
  color: #1a1a1a;
  background: #fdfdfc;
}
.nightMode.card { color: #f0efec; background: #1c1c1a; }
.term { font-size: 34px; font-weight: 600; }
.definition { font-size: 24px; }
.ipa { font-size: 18px; opacity: 0.75; }
.examples, .etymology { font-size: 17px; opacity: 0.8; margin-top: 0.7em; }
.examples { font-style: italic; }
.credit { font-size: 12px; opacity: 0.5; margin-top: 1.4em; }
.credit a { color: inherit; }
"""

RECOGNITION_FIELDS = ("Term", "Examples", "Definition", "IPA", "Etymology", "Audio", "Credit")
PRODUCTION_FIELDS = ("Definition", "Term", "IPA", "Etymology", "Credit")

RECOGNITION_FRONT = """\
<div class="term">{{Term}}</div>
{{#Examples}}<div class="examples">{{Examples}}</div>{{/Examples}}\
"""

RECOGNITION_BACK = """\
{{FrontSide}}
<hr id="answer">
<div class="definition">{{Definition}}</div>
{{#IPA}}<div class="ipa">{{IPA}}</div>{{/IPA}}
{{#Audio}}<div class="audio">{{Audio}}</div>{{/Audio}}
{{#Etymology}}<div class="etymology">{{Etymology}}</div>{{/Etymology}}
<div class="credit">{{Credit}}</div>\
"""

PRODUCTION_FRONT = """\
<div class="definition">{{Definition}}</div>\
"""

PRODUCTION_BACK = """\
{{FrontSide}}
<hr id="answer">
<div class="term">{{Term}}</div>
{{#IPA}}<div class="ipa">{{IPA}}</div>{{/IPA}}
{{#Etymology}}<div class="etymology">{{Etymology}}</div>{{/Etymology}}
<div class="credit">{{Credit}}</div>\
"""


def write(
    cards: Iterable[Card],
    path: str | Path,
    *,
    name: str,
    source: str = "a text",
    edition: str = "en",
) -> Path:
    """Write ``cards``, in the order given, as an Anki package at ``path``."""
    cards = list(cards)
    deck = genanki.Deck(
        _stable_id(f"deck:{name}"),
        name,
        DESCRIPTION.format(
            source=source,
            home=WIKTIONARY_HOME.format(edition=edition),
            license=LICENSE_URL,
        ),
    )
    models = {RECOGNITION: _recognition_model(), PRODUCTION: _production_model()}
    media = []
    for position, card in enumerate(cards, start=1):
        if card.answer.audio:
            media.append(card.answer.audio)
        deck.add_note(_note(card, models[card.kind], due=position, edition=edition))

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    genanki.Package(deck, media_files=media).write_to_file(path)
    return path


def _note(card: Card, model, *, due: int, edition: str) -> genanki.Note:
    credit = CREDIT.format(
        entry=entry_url(card.entry, edition, card.language),
        title=card.entry,
        license=LICENSE_URL,
    )
    if card.kind == RECOGNITION:
        fields = [
            card.challenge.term or "",
            _lines(card.challenge.examples),
            card.answer.definition or "",
            _readings(card.answer.ipa),
            card.answer.etymology or "",
            _sound(card.answer.audio),
            credit,
        ]
    else:
        fields = [
            card.challenge.definition or "",
            card.answer.term or "",
            _readings(card.answer.ipa),
            card.answer.etymology or "",
            credit,
        ]
    return genanki.Note(
        model=model,
        fields=fields,
        #: Identity is the card itself -- which gloss, which side -- so a
        #: rebuilt deck updates the note it already made for that card.
        guid=genanki.guid_for(card.kind, card.entry, _identity(card)),
        tags=[card.kind],
        due=due,
    )


def _identity(card: Card) -> str:
    """The gloss the card teaches, as the design identifies one."""
    term = card.challenge.term or card.answer.term or ""
    definition = card.challenge.definition or card.answer.definition or ""
    return f"{term}\n{definition}"


def _lines(values: tuple[str, ...]) -> str:
    return "<br>".join(values)


def _readings(ipa: tuple[str, ...]) -> str:
    return " ".join(ipa)


def _sound(path: str | None) -> str:
    """Anki's own reference to a media file, which is the file's bare name."""
    return f"[sound:{Path(path).name}]" if path else ""


def _recognition_model() -> genanki.Model:
    return genanki.Model(
        _stable_id("model:recognition"),
        "decker recognition",
        fields=[{"name": field} for field in RECOGNITION_FIELDS],
        templates=[
            {
                "name": "Recognition",
                "qfmt": RECOGNITION_FRONT,
                "afmt": RECOGNITION_BACK,
            }
        ],
        css=CSS,
    )


def _production_model() -> genanki.Model:
    return genanki.Model(
        _stable_id("model:production"),
        "decker production",
        fields=[{"name": field} for field in PRODUCTION_FIELDS],
        templates=[
            {
                "name": "Production",
                "qfmt": PRODUCTION_FRONT,
                "afmt": PRODUCTION_BACK,
            }
        ],
        css=CSS,
    )


def _stable_id(name: str) -> int:
    """An Anki id derived from a name, in the range Anki expects.

    genanki asks for a random id and warns that changing it makes a second
    deck; deriving it from the name instead means the deck a run produces is
    the same deck the last run produced.
    """
    digest = hashlib.sha256(name.encode("utf-8")).digest()
    return (1 << 30) + int.from_bytes(digest[:4], "big") % (1 << 30)

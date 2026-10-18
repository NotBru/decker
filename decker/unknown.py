"""Terms Wiktionary has no entry for: what they are, and what to do with each.

A run over real text always has some. The ten-language survey counted them --
twenty in the Spanish sample, thirty in the Japanese -- and decker's answer was
to print a line and drop the word. That is right for most of them and wrong for
two kinds:

* **A misspelling.** The text says `recivir`, Wiktionary has `recibir`, and the
  learner needs the word that was meant. Dropping it loses a word of the text
  for a reason that has nothing to do with the learner. The same goes for a
  capital that is an artefact -- a word at the start of a line of verse, a
  title-cased heading.
* **A foreign word the reader would not know.** A Spanish text quoting a French
  title, a Russian one using an English brand: no Spanish entry exists because
  it is not a Spanish word, and yet a reader who does not know it is stuck.

And two kinds it is right about:

* **A foreign word everyone knows.** `pizza` in a German text, `weekend` in a
  French one. A card for it teaches nothing.
* **Something unrecognizable.** A fragment, a code, a mis-tokenization.

A fourth answer, `native`, was added once the first three were measured: asked
where `perro` belonged, a model with only those three answered "foreign, and
everyone knows it" -- which is the answer that throws a word away. A word of the
language that the dictionary lacks is rare and worth having, so it is taught
with the model's own sentence, like an unfamiliar foreign one.

So the stage is one model call per distinct surface that reached the definer
with nothing, asking which of those it is, and -- for a foreign word -- whether
a reader would know it, and what to say if not. Bru's call, 2026-09-16.

The explanation is asked for in English, like a morphological rule's prose, and
the translation stage turns it into the mother language afterwards: the stage
that translates definitions is the stage that should translate this, and asking
here would be a second way of doing the same thing.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from decker.ollama import DEFAULT_MODEL, Session
from decker.translation import SOURCE_LANGUAGE

#: Wrongly-spelled and wrongly-capitalized are one answer with one remedy --
#: the word that was meant -- so they are one value with a correction, rather
#: than two the model has to tell apart before either can be acted on.
SCHEMA = {
    "type": "object",
    "properties": {
        "kind": {
            "type": "string",
            "enum": ["misspelling", "name", "foreign", "native", "unrecognizable"],
        },
        "correction": {"type": "string"},
        "language": {"type": "string"},
        "widely_known": {"type": "boolean"},
        "explanation": {"type": "string"},
    },
    "required": ["kind"],
}

PROMPT = """\
You are helping build language-learning cards from a text in {language}.

A word of the text has no {language} entry in Wiktionary. Say which of these it
is, judging it in the passage it appears in.

**A word printed inside a {language} text is not thereby a {language} word.** A
quoted title or a word of another language used as itself stays foreign,
however ordinary it looks on the page.

- "misspelling": a {language} word spelled or capitalized wrongly, or drawn out
  for effect -- a vowel stretched, a letter repeated, the way speech is written
  in comics and chat. Put the word that was meant in "correction", spelled as a
  dictionary would; for a drawn-out word, that is the word with the stretch
  taken out, not another word that happens to look like it. Only when the
  passage would accept that word in that place.
- "name": the name of a person, place, group, shop or thing in the text --
  a character, a street, a company -- whatever language it comes from. Write
  "explanation": one plain sentence in {source} that starts with the name
  written in Latin letters and says what kind of name it is -- a given name,
  a family name, a place, a shop -- and nothing more.
- "foreign": a word of another language. Name that language in
  "language". Then answer "widely_known": true if a reader of {language} would
  recognise it unaided -- an everyday borrowing, a household name -- false if
  not. When false, write "explanation": one plain sentence in {source} saying
  what it is and where it is from.
- "native": an ordinary {language} word that Wiktionary happens not to have --
  regional, rare, very new. Answer this **only** if you are confident that
  {language} speakers use it as their own word; if it might belong to another
  language, it is "foreign". Write "explanation": one plain sentence in
  {source} saying what it means.
- "unrecognizable": not a word at all -- a fragment, a code, a symbol, several
  words run together by a bad split, or something you cannot place. Nothing to
  teach.

**An explanation says what the word is, never what happens in the text.** The
passage is there for you to judge the word by; the card is read before the
story is, so it names no character, event or place of the story and says
nothing about who speaks, to whom, or why.

Prefer "unrecognizable" to a guess. An explanation you are not sure of is worse
than no card: the learner cannot tell the two apart.

Passage, one sentence or speech bubble to a line:
{passage}

The word: {surface}

Answer with the kind, and the other fields that kind asks for.
"""

#: No context in an explanation, by Bru's instruction of 2026-10-18: the
#: name prompt had asked for "whom or what it names as far as the passage
#: shows", and `タオ` came back as the man who answers the office's phone --
#: a card that tells the story before the reader has read it.
#:
#: What a card says when the model wrote its explanation. A foreign word has no
#: Wiktionary entry at all -- that is why it is here -- so the card cannot
#: credit one, and must not look as though it does.
ATTRIBUTION = "Explained by {model}; this word has no Wiktionary entry."


@dataclass(frozen=True)
class Verdict:
    """What the model made of one word with no entry."""

    kind: str
    correction: str = ""
    widely_known: bool = False
    explanation: str = ""

    @property
    def is_correction(self) -> bool:
        return self.kind == "misspelling" and bool(self.correction)

    @property
    def is_teachable_foreign(self) -> bool:
        return (
            self.kind == "foreign"
            and not self.widely_known
            and bool(self.explanation)
        )

    @property
    def is_native(self) -> bool:
        """A word of the language itself, which the dictionary simply lacks.

        Added after the three-way split was measured: asked to place `perro` in
        it, the model answered "foreign, widely known", which is the answer that
        drops a word. A word the extractor found, the parser lemmatised and
        Wiktionary has no page for is the most interesting thing this stage
        sees, not the least, and it is taught with the model's sentence exactly
        as an unfamiliar foreign word is.
        """
        return self.kind == "native" and bool(self.explanation)

    @property
    def is_name(self) -> bool:
        """A name in the text, which a reader needs to tell from a word.

        Added with untitled words, 2026-10-18: a name is the commonest word
        with no page at all, and a reader who meets `タオさん` needs to know
        `タオ` is somebody before `さん` means anything.
        """
        return self.kind == "name" and bool(self.explanation)


@dataclass
class Unknowns:
    """The stage, and what it decided, for the run's report."""

    lang: str
    model: str = DEFAULT_MODEL
    host: str | None = None
    refresh: bool = False
    #: `off` leaves every entry-less term dropped, which is what decker did
    #: before this existed; `fix` is the design's answer; `all` also teaches
    #: the foreign words a reader is expected to know already.
    mode: str = "fix"
    session: Session = field(init=False)
    decided: dict[str, Verdict] = field(default_factory=dict, init=False)

    def __post_init__(self) -> None:
        self.session = Session(
            model=self.model,
            host=self.host,
            refresh=self.refresh,
            what="unknown words",
        )

    @property
    def enabled(self) -> bool:
        return self.mode != "off"

    def verdict(self, surface: str, passage: str, language: str) -> Verdict | None:
        """What this word is, asked once however often the text says it."""
        if not self.enabled:
            return None
        if surface in self.decided:
            return self.decided[surface]
        answer = self.session.ask(
            PROMPT.format(
                language=language,
                source=SOURCE_LANGUAGE,
                passage=passage,
                surface=surface,
            ),
            SCHEMA,
        )
        verdict = _read(answer)
        if verdict is not None:
            self.decided[surface] = verdict
        return verdict

    def teaches_known_foreign(self) -> bool:
        return self.mode == "all"

    def report(self) -> tuple[str, ...]:
        """One line per kind decided, for whoever is reading the run."""
        if not self.decided:
            return ()
        kinds: dict[str, int] = {}
        for verdict in self.decided.values():
            name = verdict.kind
            if name == "foreign":
                name = "foreign, known" if verdict.widely_known else "foreign, explained"
            kinds[name] = kinds.get(name, 0) + 1
        parts = ", ".join(f"{count} {kind}" for kind, count in sorted(kinds.items()))
        return (f"[decker] {len(self.decided)} words had no entry: {parts}",)


def _read(answer: dict | None) -> Verdict | None:
    """The model's answer as a verdict, or nothing if it is not one."""
    if not isinstance(answer, dict):
        return None
    kind = answer.get("kind")
    if kind not in ("misspelling", "name", "foreign", "native", "unrecognizable"):
        return None
    return Verdict(
        kind=kind,
        correction=str(answer.get("correction") or "").strip(),
        widely_known=bool(answer.get("widely_known")),
        explanation=str(answer.get("explanation") or "").strip(),
    )

"""Sense disambiguation: which of a page's senses the sentence actually uses.

A Wiktionary page lists every sense a word has ever had; a card built from all
of them teaches noise. The design puts this choice in the hands of a local
model served by ollama, asked one term at a time and answering with the sense
numbers it keeps.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from decker.ollama import DEFAULT_MODEL, Session
from decker.pages import Sense

SCHEMA = {
    "type": "object",
    "properties": {
        "senses": {"type": "array", "items": {"type": "integer"}},
    },
    "required": ["senses"],
}

#: Every prompt puts its fixed instructions first and its variable parts last,
#: so that consecutive calls share as long a common prefix as possible. Ollama
#: keeps the prefill of that prefix between calls and re-reads only the tail,
#: which on a laptop's CPU is most of the cost: the answer is a handful of
#: tokens, the sense listing that precedes it is hundreds. A short restatement
#: of the task follows the listing, since instructions sitting far from the end
#: of a long prompt are the ones a small model drifts from -- it comes after
#: the prefix has already diverged, so it is free.
PROMPT = """\
You are helping build language-learning cards from a text in {language}.

You will be shown a short passage, one term occurring in it marked ⟨like
this⟩, and the numbered senses of the Wiktionary page(s) that term belongs to.
Judge the marked occurrence only: the same word elsewhere in the passage may
well be a different one, and the sentences around the marked one are there for
context.

Reply with the numbers of the senses this occurrence actually uses. Each sense
you keep becomes a flashcard of its own, so keep as few as truly apply --
usually exactly one. Keep more only where the occurrence genuinely carries more
than one meaning at once, not merely because a sense is nearby or related. If
none fit, keep the single closest one.

Passage: {sentence}
Term as it appears: {surface}{reading}
Numbered senses of the Wiktionary page(s) {title}:
{senses}

Reply with the numbers of the senses the marked occurrence actually uses.
"""

#: What the parse's reading of the occurrence is worth saying as, and how much
#: it is worth. Added because of Hebrew: Stanza splits the clitic prefixes off,
#: as it should, and the page for a one-letter token offers both the
#: preposition and the name of the letter of the alphabet. A sentence-context
#: prompt gives a small model nothing to choose between them with, and it chose
#: the letter five times over -- the five most frequent prefixes in the
#: language, at the front of the deck, each teaching the wrong thing. The parse
#: knew all along: the token is an adposition. It is a hint and not an
#: instruction, because a parse is wrong sometimes and Wiktionary's part of
#: speech is not always UD's.
READING = """
The parse reads the marked occurrence as {reading}. Prefer a sense listed under
that part of speech; choose one listed under another only where the sentence
plainly demands it."""

#: UD's tags, as a prompt says them. Wiktionary's own part-of-speech headings
#: are the words on the other side of this -- `Preposition`, `Letter`, `Verb`
#: -- so the wording leans towards them where the two agree.
READINGS = {
    "ADJ": "an adjective",
    "ADP": "an adposition (a preposition or a postposition)",
    "ADV": "an adverb",
    "AUX": "an auxiliary verb",
    "CCONJ": "a coordinating conjunction",
    "DET": "a determiner or article",
    "INTJ": "an interjection",
    "NOUN": "a noun",
    "NUM": "a numeral",
    "PART": "a particle",
    "PRON": "a pronoun",
    "PROPN": "a proper noun",
    "SCONJ": "a subordinating conjunction",
    "VERB": "a verb",
}


def reading_of(upos: str) -> str:
    """The sentence to hand the model about ``upos``, or nothing.

    Nothing for the tags that say only what a thing is not -- `X`, `SYM`,
    `PUNCT` -- since a hint the model cannot act on is prompt spent for
    nothing.
    """
    named = READINGS.get(upos.upper())
    return READING.format(reading=named) if named else ""


#: Asked when the word is not in the text at all, but is referenced by a
#: definition that describes another word in terms of it. One sense is wanted:
#: the reader needs the meaning the reference relies on, not the word's range.
PROMPT_ONE = """\
You are helping build language-learning cards from a text in {language}.

You will be shown a short passage, a word that some definition in it describes
another word in terms of, and the numbered senses of that word's Wiktionary
page(s).

Reply with the number of the ONE sense that the description relies on -- the
meaning a reader has to know for that description to make sense. Exactly one
number.

Passage: {sentence}
The word being described in terms of: "{surface}"
Numbered senses of the Wiktionary page(s) {title}:
{senses}

Reply with exactly one sense number.
"""


@dataclass
class Disambiguator:
    """Picks senses through ollama, or keeps everything when it cannot."""

    model: str = DEFAULT_MODEL
    host: str | None = None
    #: Ask the model again even when the answer is cached.
    refresh: bool = False
    enabled: bool = True
    session: Session = field(init=False)

    def __post_init__(self) -> None:
        self.session = Session(
            model=self.model,
            host=self.host,
            refresh=self.refresh,
            what="sense disambiguation",
            fallback="keeping every sense",
        )

    def keep(
        self,
        senses: tuple[Sense, ...],
        *,
        sentence: str,
        surface: str,
        title: str,
        language: str,
        parts_of_speech: tuple[str, ...] = (),
        sources: tuple[str, ...] = (),
        upos: str = "",
        single: bool = False,
    ) -> tuple[Sense, ...]:
        """Return the senses worth glossing, in their original order.

        ``sources`` names the page each sense came from, so a term pooled
        from more than one spelling shows the model which entry is which.
        ``upos`` is the parse's reading of the occurrence, passed on as a
        hint where there is one; a word reached through a definition rather
        than through the text has no occurrence to read, and none.
        """
        if not self.enabled or len(senses) <= 1:
            return senses[:1] if single else senses
        listing = "\n".join(
            f"{number}. {_labelled(sense, parts_of_speech, sources, number - 1)}"
            for number, sense in enumerate(senses, start=1)
        )
        prompt = (
            PROMPT_ONE.format(
                language=language,
                sentence=sentence,
                surface=surface,
                title=title,
                senses=listing,
            )
            if single
            else PROMPT.format(
                language=language,
                sentence=sentence,
                surface=surface,
                reading=reading_of(upos),
                title=title,
                senses=listing,
            )
        )
        chosen = self._ask(prompt)
        if chosen is None:
            return senses[:1] if single else senses
        kept = tuple(
            sense
            for number, sense in enumerate(senses, start=1)
            if number in chosen
        ) or senses
        return kept[:1] if single else kept

    def _ask(self, prompt: str) -> set[int] | None:
        answer = self.session.ask(prompt, SCHEMA)
        if answer is None:
            return None
        try:
            return {int(number) for number in answer.get("senses", ())}
        except (TypeError, ValueError) as error:  # a schema the model bent
            self.session.warn(str(error))
            return None


def _labelled(
    sense: Sense,
    parts_of_speech: tuple[str, ...],
    sources: tuple[str, ...],
    index: int,
) -> str:
    part = parts_of_speech[index] if index < len(parts_of_speech) else ""
    source = sources[index] if index < len(sources) else ""
    if source and len(set(sources)) > 1:
        part = f"{source}, {part}" if part else source
    return f"({part}) {sense.definition}" if part else sense.definition

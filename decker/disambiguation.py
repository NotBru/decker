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


#: Said in place of the reading when the parse's `PROPN` is the capital's
#: doing. Withholding the tag was tried first and was not enough: with the
#: hint gone, `qwen3.5:4b` still read `Надежда казалась мне солью` as the name,
#: the capital in the passage being signal enough on its own. So the thing
#: decker knows is said outright -- term extraction has already decided the
#: capital is suspect, and the lower-case entry is in the listing because of
#: it, which the model has no way to see.
#:
#: The last clause is the one that does the work, and this wording is held
#: together loosely. *Judge it as though it were written in lower case* turns
#: the answer over; the same claim without it -- "its capital is the line's and
#: says nothing about the word" -- leaves `Надежда` the given name, and so does
#: the same sentence rearranged around an em-dash parenthetical. That is a 4B
#: at the edge of what it can do rather than a prompt with a missing
#: instruction: `gemma4:latest` and `gpt-oss:20b` answer *hope* under every
#: wording tried, including the wrong `PROPN` hint this replaced. Measured
#: 2026-09-17, on the deck Bru was about to study.
CAPITAL = """
The marked occurrence begins its line or its sentence, and a word in that
position takes a capital whatever it is, so its capital says nothing about the
word: judge it as though it were written in lower case, from what the passage
means."""


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
        positional_capital: bool = False,
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
        prompt = self.question(
            senses,
            sentence=sentence,
            surface=surface,
            title=title,
            language=language,
            parts_of_speech=parts_of_speech,
            sources=sources,
            upos=upos,
            positional_capital=positional_capital,
            single=single,
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

    def question(
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
        positional_capital: bool = False,
        single: bool = False,
    ) -> str:
        """The exact prompt this choice is made with.

        Its own method because two callers have to produce the same string:
        :meth:`keep`, which asks and reads the answer, and :meth:`warm`, which
        asks ahead of the run so that `keep` finds the answer already on disk.
        A prompt that differed by a space between them would warm nothing and
        pay for every question twice.
        """
        listing = "\n".join(
            f"{number}. {_labelled(sense, parts_of_speech, sources, number - 1)}"
            for number, sense in enumerate(senses, start=1)
        )
        if single:
            return PROMPT_ONE.format(
                language=language,
                sentence=sentence,
                surface=surface,
                title=title,
                senses=listing,
            )
        return PROMPT.format(
            language=language,
            sentence=sentence,
            surface=surface,
            reading=CAPITAL if positional_capital else reading_of(upos),
            title=title,
            senses=listing,
        )

    def warm(self, prompt: str) -> None:
        """Ask a question whose answer nobody is waiting for yet.

        The answer goes to the cache and is dropped here; what it buys is the
        model working while the run is on the network, and two questions in
        flight instead of one. A failure is nothing to report -- the question
        will be asked again where it is needed, and `keep` will report it
        there.
        """
        if not self.enabled:
            return
        self.session.ask(prompt, SCHEMA)

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

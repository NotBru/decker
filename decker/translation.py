"""Translation: a gloss written in the mother language.

Glosses are quoted from a Wiktionary edition, so they are written in that
edition's language -- English, for v1's ``en``. A learner whose mother tongue
is something else needs the same gloss in it, which the design puts in deck
construction and v1 puts through ollama, the same way sense disambiguation
goes through it.

The mother tongue is named by a code, the way every other language decker is
told about is; the prompt below is the only thing that wants it as a word, and
:mod:`decker.languages` is where the code becomes one.

Only the prose is translated. An example arrives as a pair -- the sentence in
the target language, the edition's rendering of it -- and the rendering is
what is sent, so that no answer can rewrite the very thing the card is
teaching. That holds for every example, including the ones whose sentence
contains the em dash the two halves are shown with, which is why
:class:`decker.pages.Example` keeps them apart rather than joining them and
cutting the string up again here. The headword and the forms a definition
names are still asked to survive untouched, because they are inside the
definition and cannot be held back from it.

A sentence does reach the model in one case -- :meth:`Translator.rendered`,
where the edition gave no rendering to send in its place -- and the rule
survives it whole, because what comes back is used only as the rendering. The
sentence on the card is always the sentence that arrived. Nothing here can
replace it; the most a bad answer can do is put bad prose under it, which is
what a bad translation of a rendering does anyway.

Two more things are asked for that Wiktionary did not write. One is the title
of a card decker titles itself -- a concept, a morphological rule -- which is
decker's prose and is read in the mother tongue like any other, so
:meth:`Translator.title` puts it there; see :func:`decker.cards._titled` for
which half of a title is prose and which half is quoted from the language. The
other is :meth:`Translator.equivalent`, the mother tongue's own word for a
sense, which only a deck whose target language is the edition's own has any
need of: see :func:`decker.cards._equivalent`.
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter
from dataclasses import dataclass, field

from decker.console import log
from decker.languages import name_of
from decker.ollama import DEFAULT_MODEL, Session
from decker.pages import Example

#: The language a gloss arrives in: the edition's own, which v1 fixes at the
#: English Wiktionary. A mother language other than this one is what makes
#: translation happen at all. The code is what decker is told and what the
#: comparison is made on; the name is for the prompt, and only there.
SOURCE_LANG = "en"
SOURCE_LANGUAGE = "English"

SCHEMA = {
    "type": "object",
    "properties": {
        "definition": {"type": "string"},
        "examples": {"type": "array", "items": {"type": "string"}},
        "etymology": {"type": "string"},
    },
    #: The etymology is required, and that is the whole of what once looked
    #: like a translation the model got wrong. Left optional, ollama's
    #: structured output let the model omit the field; an omitted field is an
    #: empty one, an empty one falls back to the text that was sent, and the
    #: card carried the English original with nothing in the run saying so.
    #: Required, the same model translates every one of them.
    "required": ["definition", "examples", "etymology"],
}

#: Fixed instructions first, the gloss last, so that consecutive calls share
#: as long a prefix as ollama can keep prefilled between them -- the same
#: shape, and for the same reason, as the disambiguation prompts.
PROMPT = """\
You are helping build language-learning cards for a speaker of {mother}, from
a dictionary written in {source} that teaches {target}.

You will be shown one definition, the {source} renderings of the examples
under it, and its etymology -- all of it written in {source}. Put all of it
into {mother}, keeping the meaning exact and the wording plain and short.

The headword and any form of it the definition names are quoted from {target}
and stay exactly as they are; translate the {source} around them. Answer with
the same number of examples, in the same order. If there is no etymology,
answer with an empty one.

Definition: {definition}
Examples: {examples}
Etymology: {etymology}

Answer in {mother}.
"""

#: The field is called `translated` and that is not a detail. Called `name`,
#: which is what it holds, both gemma3:4b and gemma4 answered `present tense`
#: to `present tense` -- 33 of 47 glossary names came back untouched from the
#: bigger of the two, some with the instructions themselves appended. The key
#: a structured answer is asked for is read as part of the instruction, and a
#: key naming the input asks for the input. Renaming it, and changing nothing
#: else, translated all 47.
TITLE_SCHEMA = {
    "type": "object",
    "properties": {"translated": {"type": "string"}},
    "required": ["translated"],
}

TITLE_PROMPT = """\
You are helping build language-learning cards for a speaker of {mother}, from
a dictionary written in {source} that teaches {target}.

You will be shown one short {source} phrase from the heading of a card: the
name of a grammatical term, or the word saying which kind of card it is. Put
it into {mother}, using the name {mother}'s own grammars use rather than a
word-by-word rendering.

Say the whole of it: a name saying which tense, which person, which number or
which part of speech has to go on saying it in {mother}. It is a heading, so
answer with the phrase alone -- no article, no explanation, no full stop -- and
written the way it would be written in the middle of a sentence.

{source} phrase: {phrase}

Answer in {mother}.
"""


RENDERING_SCHEMA = {
    "type": "object",
    "properties": {
        "renderings": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["renderings"],
}

#: The examples of a gloss the edition has no rendering for. An English
#: dictionary prints an English sentence and stops, because to its own reader
#: the sentence is already in the language it is read in; a Spanish speaker
#: studying English is handed the sentence and nothing else. Same shape as the
#: prompt above, and the sentences are the whole of what is sent because here
#: there is no rendering to send in their place.
RENDERING_PROMPT = """\
You are helping build language-learning cards for a speaker of {mother}, from
a dictionary written in {source} that teaches {target}.

You will be shown example sentences in {target}, quoted from that dictionary,
which prints them with no rendering beside them because it is written in
{target} itself. Put each sentence into {mother}, plainly and close to its
wording, so that the back of a card can say what the sentence on its front
says.

Answer with the same number of sentences, in the same order, and nothing else.

Sentences: {sentences}

Answer in {mother}.
"""

EQUIVALENT_SCHEMA = {
    "type": "object",
    "properties": {"translated": {"type": "string"}},
    "required": ["translated"],
}

#: The one thing a deck built from the English Wiktionary for an English
#: learner has no way to say. Every other deck gets the mother tongue's word
#: for free: `todavía`'s entry is *still*, because the edition is written in
#: the mother tongue's direction. Turn it around -- teach English to a Spanish
#: speaker -- and the entry for `still` describes the word instead, and no
#: amount of translating that description produces the word `todavía`.
EQUIVALENT_PROMPT = """\
You are helping build language-learning cards for a speaker of {mother}, from
a dictionary written in {source} that teaches {target}.

The dictionary is written in the language it is teaching here, so it describes
this word rather than rendering it: `still` gets a definition, never the word
a {mother} speaker would say instead. The card needs that word.

You will be shown one word and the one sense the card teaches it in. Answer
with the {mother} word or short phrase a {mother} speaker uses for it in that
sense, and with nothing else -- no explanation, no full stop, and no more
alternatives than a dictionary would separate with a comma. Answer with the
sense that is asked for and not the word's commonest one.

Word: {term}
Sense: {definition}

Answer in {mother}.
"""


@dataclass
class Translator:
    """Puts a gloss into the mother language, or leaves it as it came."""

    mother_lang: str = SOURCE_LANG
    model: str = DEFAULT_MODEL
    host: str | None = None
    #: Ask the model again even when the answer is cached.
    refresh: bool = False
    enabled: bool = True
    session: Session = field(init=False)
    #: Glosses already translated this run, keyed by the text asked about: a
    #: sense met by two terms is one call, not two.
    done: dict[tuple, tuple] = field(default_factory=dict, init=False)
    #: Fields that reached a card in the source language anyway, by kind. A
    #: model that answers with nothing, or with the very text it was handed,
    #: leaves prose the fallbacks below then restore -- correctly, since an
    #: untranslated right sentence beats a translated wrong one, but silently.
    #: Counting them is what lets a run say so instead of the reader finding
    #: out from the cards.
    kept: Counter[str] = field(default_factory=Counter, init=False)
    #: Titles already put into the mother language this run, keyed by what
    #: was asked about. `Concept: ` is one entry of it and so is asked once for
    #: the whole run, however many concepts the text needs.
    titles: dict[tuple, str] = field(default_factory=dict, init=False)
    #: Renderings written for sentences the edition printed bare, keyed by the
    #: sentences asked about together: one gloss's worth is one call.
    renderings: dict[tuple, tuple[str, ...]] = field(default_factory=dict, init=False)
    #: The mother tongue's own word for a sense, keyed by word and sense.
    equivalents: dict[tuple, str] = field(default_factory=dict, init=False)

    def __post_init__(self) -> None:
        self.session = Session(
            model=self.model,
            host=self.host,
            refresh=self.refresh,
            what="translation",
        )

    @property
    def needed(self) -> bool:
        """Whether anything has to be translated at all.

        v1's mother language is the edition's, so the usual run answers no
        here and never opens a connection.
        """
        code = self.mother_lang.strip().casefold()
        return self.enabled and bool(code) and code != SOURCE_LANG

    def gloss(
        self,
        *,
        definition: str,
        examples: tuple[Example, ...],
        etymology: str | None,
        target_language: str,
    ) -> tuple[str, tuple[Example, ...], str | None]:
        """The three pieces of prose a gloss carries, in the mother language."""
        if not self.needed:
            return definition, examples, etymology
        key = (definition, examples, etymology, target_language)
        if key not in self.done:
            self.done[key] = self._ask(
                definition=definition,
                examples=examples,
                etymology=etymology,
                target_language=target_language,
            )
        return self.done[key]

    def rendered(
        self, examples: tuple[Example, ...], *, target_language: str
    ) -> tuple[Example, ...]:
        """The examples, with a rendering under the ones that had none.

        Wiktionary renders an example when the example is not in the
        edition's language, which is every deck but one: a Spanish sentence
        under a Spanish entry comes with its English beside it, and the
        rendering is what :meth:`gloss` translates. An English sentence under
        an English entry comes alone -- correctly, for a reader of English --
        and a deck teaching English to a Spanish speaker then shows a sentence
        with nothing under it. So the sentences that arrived unrendered get a
        rendering here.

        The sentence itself is still never replaced by what comes back. The
        rule the rest of this module keeps -- the card teaches the sentence,
        so the model must not be able to rewrite it -- is kept by using the
        answer only as the rendering, which is the half of the pair the model
        is allowed to write. An answer that does not line up one for one is
        refused whole, for the reason :func:`_examples` gives.
        """
        if not self.needed:
            return examples
        bare = tuple(
            example.sentence
            for example in examples
            if example.sentence and not example.rendering
        )
        if not bare:
            return examples
        key = (bare, target_language)
        if key not in self.renderings:
            self.renderings[key] = self._ask_renderings(bare, target_language)
        answered = self.renderings[key]
        if len(answered) != len(bare):
            return examples
        filled = iter(answered)
        return tuple(
            example
            if example.rendering or not example.sentence
            #: ``None`` and not ``""``: an empty rendering is no rendering,
            #: and `Example.__str__` tells the two apart.
            else Example(example.sentence, next(filled) or None)
            for example in examples
        )

    def _ask_renderings(
        self, sentences: tuple[str, ...], target_language: str
    ) -> tuple[str, ...]:
        prompt = RENDERING_PROMPT.format(
            mother=name_of(self.mother_lang),
            source=SOURCE_LANGUAGE,
            target=target_language or "the target language",
            sentences=json.dumps(list(sentences), ensure_ascii=False),
        )
        answer = self.session.ask(prompt, RENDERING_SCHEMA)
        answered = answer.get("renderings") if isinstance(answer, dict) else None
        if not isinstance(answered, list) or len(answered) != len(sentences):
            if answer:
                self.kept["example unrendered"] += len(sentences)
            return ()
        #: An empty answer is no rendering, and a sentence handed back as its
        #: own rendering is the card saying the same thing twice -- both leave
        #: the example as it arrived, which is the sentence alone.
        put = tuple(
            _MARKER.sub("", str(one)).strip() for one in answered
        )
        put = tuple("" if one == was else one for one, was in zip(put, sentences))
        if bare := sum(1 for one in put if not one):
            self.kept["example unrendered"] += bare
        return put

    def equivalent(self, *, term: str, definition: str, target_language: str) -> str:
        """The mother tongue's own word for a sense, where the deck needs one.

        Only where the language being taught is the language the dictionary is
        written in, which the caller decides; everywhere else the definition
        *is* the mother tongue's word for the sense and asking for a second
        one would put a paraphrase in front of a translation.
        """
        if not self.needed or not term or not definition:
            return ""
        key = (term, definition, target_language)
        if key not in self.equivalents:
            self.equivalents[key] = self._ask_equivalent(
                term, definition, target_language
            )
        return self.equivalents[key]

    def _ask_equivalent(
        self, term: str, definition: str, target_language: str
    ) -> str:
        prompt = EQUIVALENT_PROMPT.format(
            mother=name_of(self.mother_lang),
            source=SOURCE_LANGUAGE,
            target=target_language or "the target language",
            term=term,
            definition=definition,
        )
        answer = self.session.ask(prompt, EQUIVALENT_SCHEMA)
        word = answer.get("translated") if isinstance(answer, dict) else None
        if not isinstance(word, str) or not word.strip():
            if answer:
                self.kept["equivalent empty"] += 1
            return ""
        word = _MARKER.sub("", word).strip().rstrip(".").strip()
        #: The word itself handed back is worse than nothing: this line sits
        #: on the question side of the production card, which asks for that
        #: very word. Counted and dropped.
        if word.casefold() == term.casefold():
            self.kept["equivalent echoed"] += 1
            return ""
        return word

    def title(
        self,
        *,
        prefix: str,
        prose: str,
        target_language: str = "",
    ) -> str:
        """decker's own title for a card, in the mother language.

        A title decker writes is in two halves and only one of them is prose:
        `Concept: ` and `Rule: ` say which pile the card is in, and the name
        after them -- `ditransitive verb`, `comparative form` -- is the
        grammatical term the card is about. Both are English because the
        glossary decker read them out of is, neither is a word of the language
        being taught, and a learner reading a Spanish description under
        `Concept: negative polarity item` is being asked to know English to
        study English. So both go through the model, separately: the pile's
        word once for the run, the term with the card's own text beside it.

        What is *not* here is the rest of the title, which the caller keeps:
        the word quoted from the language a rule is named after -- the
        `(older)` in `Rule: comparative form (older)` -- is the thing being
        taught, and translating it would teach the wrong word.
        """
        if not self.needed or not prose:
            return f"{prefix}{prose}"
        return (
            self._pile(prefix, target_language)
            + self._phrase(prose, target_language)
        )

    def _pile(self, prefix: str, target_language: str) -> str:
        """`Concept: ` in the mother language, punctuation and spacing kept.

        Only the word is sent -- the colon and the space are the title's
        shape, not its language, and a model handed them back the answer with
        its own idea of both.
        """
        word = prefix.strip(": ")
        if not word:
            return prefix
        return prefix.replace(word, self._phrase(word, target_language), 1)

    def _phrase(self, text: str, target_language: str) -> str:
        """One heading's worth of prose, asked for once per run."""
        key = (text, target_language)
        if key not in self.titles:
            self.titles[key] = self._ask_title(text, target_language)
        return self.titles[key]

    def _ask_title(self, text: str, target_language: str) -> str:
        """The heading alone, with nothing of the card's own text beside it.

        Offering the card's description as context is the obvious improvement
        and it made the answers worse, measured twice over the 47 glossary
        names an English deck of nine Spanish-subtitled episodes pulled in.
        The model stopped naming the term and started translating the
        description: `present tense` and `past tense` both came back
        `tiempo verbal`, one title for two cards, and once the schema's field
        was renamed (see :data:`TITLE_SCHEMA`) whole sentences came back --
        `Concepto: El tiempo verbal que se usa principalmente para referirse
        a un evento...`. Alone, 43 of the 47 are the term a Spanish grammar
        would use. What the context was meant to fix -- a one-word name with
        an everyday sense, `focus`, `literal` -- turned out to be the field
        name's doing and not the context's absence.
        """
        prompt = TITLE_PROMPT.format(
            mother=name_of(self.mother_lang),
            source=SOURCE_LANGUAGE,
            target=target_language or "the target language",
            phrase=text,
        )
        answer = self.session.ask(prompt, TITLE_SCHEMA)
        name = answer.get("translated") if isinstance(answer, dict) else None
        if answer:
            #: Counted the way a definition is, echoes and all, although a
            #: heading of one word is the place where an echo is most often
            #: honest -- `copula` and `litotes` are Spanish for themselves. A
            #: cognate counted is an over-report the reader can discount from
            #: the cards; an echo not counted is a card in English the run
            #: never mentioned, and gemma3:4b hands back `present tense`
            #: unchanged often enough that the tally has to show it.
            self.kept.update(_kept("title", name, text))
        if not isinstance(name, str) or not name.strip():
            return text
        #: A heading with a full stop after it was asked for without one; the
        #: prompt says so and a small model adds one anyway.
        return _MARKER.sub("", name).strip().rstrip(".").strip()

    def _ask(
        self,
        *,
        definition: str,
        examples: tuple[Example, ...],
        etymology: str | None,
        target_language: str,
    ) -> tuple[str, tuple[Example, ...], str | None]:
        sent = tuple(
            example.rendering for example in examples if example.rendering
        )
        prompt = PROMPT.format(
            mother=name_of(self.mother_lang),
            source=SOURCE_LANGUAGE,
            target=target_language or "the target language",
            definition=definition,
            examples=json.dumps(list(sent), ensure_ascii=False),
            etymology=etymology or "(none)",
        )
        answer = self.session.ask(prompt, SCHEMA)
        if not answer or not isinstance(answer.get("definition"), str):
            #: A call that was never answered is the session's warning to
            #: make, once for the whole run; it is not this count's business.
            return definition, examples, etymology
        self._count(answer, definition=definition, sent=sent, etymology=etymology)
        return (
            answer["definition"].strip() or definition,
            _examples(answer.get("examples"), examples, sent),
            _etymology(answer.get("etymology"), etymology),
        )

    def _count(
        self,
        answer: dict,
        *,
        definition: str,
        sent: tuple[str, ...],
        etymology: str | None,
    ) -> None:
        """Tally the fields that will reach a card in the source language."""
        self.kept.update(_kept("definition", answer.get("definition"), definition))
        self.kept.update(_kept("etymology", answer.get("etymology"), etymology))
        answered = answer.get("examples")
        if not sent:
            return
        if not isinstance(answered, list) or len(answered) != len(sent):
            self.kept["examples refused"] += 1
            return
        for was, got in zip(sent, answered):
            self.kept.update(_kept("example", got, was))

    def report(self) -> None:
        """Say how much prose reached the cards untranslated, if any did."""
        if not self.kept:
            return
        parts = ", ".join(f"{count} {kind}" for kind, count in sorted(self.kept.items()))
        log(
            f"[decker] {sum(self.kept.values())} fields kept their "
            f"{SOURCE_LANGUAGE}: {parts}",
            kind="warn",
        )


def _kept(field: str, answered: object, original: str | None) -> dict[str, int]:
    """Whether one field will carry its source text onto a card, and why.

    Two shapes reach a card untranslated and neither is an error: an empty
    answer, which the fallbacks below replace with what was sent, and an echo,
    which is the text that was sent handed straight back. The second is a
    well-formed string that no schema can refuse, so counting is the only
    place it can be noticed at all.
    """
    if original is None:
        return {}
    text = answered.strip() if isinstance(answered, str) else ""
    if not text:
        return {f"{field} empty": 1}
    if _MARKER.sub("", text) == original.strip():
        return {f"{field} echoed": 1}
    return {}


#: A small model copies the shape it is shown, markers and all: asked with a
#: bulleted list, qwen3:1.7b answered "- Mi tío es..." every single call. The
#: prompt shows a JSON array now, which is the shape of the answer itself, so
#: there is no marker to copy -- but a marker belongs to a list and never to a
#: sentence, so one that turns up anyway is taken off here rather than shown
#: on a card.
_MARKER = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s+")


def _examples(
    answered: object,
    examples: tuple[Example, ...],
    sent: tuple[str, ...],
) -> tuple[Example, ...]:
    """The examples with their renderings translated, or exactly as they came.

    Only the renderings were sent, so only they can come back, and each one is
    put back beside the sentence it belongs to. A model that drops or merges
    one has changed which sentence teaches what, so an answer that does not
    line up one for one is refused whole.
    """
    if not sent or not isinstance(answered, list) or len(answered) != len(sent):
        return examples
    translated = iter(answered)
    rebuilt = []
    for example in examples:
        if not example.rendering:
            rebuilt.append(example)
            continue
        answer = _MARKER.sub("", str(next(translated))).strip()
        rebuilt.append(Example(example.sentence, answer or example.rendering))
    return tuple(rebuilt)


def _etymology(answered: object, original: str | None) -> str | None:
    if original is None:
        return None
    if not isinstance(answered, str) or not answered.strip():
        return original
    return answered.strip()

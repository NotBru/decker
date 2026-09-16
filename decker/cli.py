"""Command line entry point for the v1 pipeline."""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from pathlib import Path

from decker import anki, console, languages, markdown, pages, pipeline, shuffling, subtitles
from decker.wiktionary import USER_AGENT
from decker.ollama import DEFAULT_HOST, DEFAULT_MODEL, MODEL_VARIABLE, default_model
from decker.translation import SOURCE_LANG

#: Every stage runs in one go; the subcommands below stop the pipeline early.
DEFAULT_COMMAND = "deck"
COMMANDS = ("extract", "define", "deck", "index")


def main(argv: list[str] | None = None) -> int:
    try:
        return _main(argv)
    except pages.Refused as refusal:
        #: Loudly, and with a non-zero status: every later fetch would be
        #: refused the same way, and a run that carried on would finish
        #: "successfully" with a deck missing most of its glosses.
        console.log(
            f"[decker] Wikimedia refused the request (HTTP 403) for {refusal}.\n"
            "[decker] That is the client being turned away, not a missing page: "
            "usually the User-Agent policy or a blocked address.\n"
            f"[decker] decker identifies itself as {USER_AGENT!r}.\n"
            "[decker] Nothing further would succeed, so the run stopped here.",
            level=console.QUIET, kind="error",
        )
        return 2


def _main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or (argv[0] not in COMMANDS and argv[0] not in ("-h", "--help")):
        argv.insert(0, DEFAULT_COMMAND)

    parser = argparse.ArgumentParser(
        prog="decker",
        description=(
            "Build language-learning material from a text. With no subcommand the "
            "whole pipeline runs, which is what `deck` does; `extract`, `define` and "
            "`index` stop it early."
        ),
        #: Every flag belongs to a subcommand, so this help has none to show --
        #: which reads as decker having none at all, `--target-lang` included,
        #: and that is the first thing a reader needs. It cannot be fixed by
        #: showing `deck`'s flags here, since the subcommand list is what this
        #: help is for; so it says where they are.
        epilog=(
            "The flags belong to the subcommands: `decker deck -h` lists the ones a "
            "full run takes, and they are the ones that apply when no subcommand is "
            "given. Every run needs --target-lang. `decker extract -h`, `decker "
            "define -h` and `decker index -h` list the rest."
        ),
    )
    subcommands = parser.add_subparsers(dest="command", required=True)

    extract = subcommands.add_parser(
        "extract", help="extract the terms of a source text and stop there"
    )
    extract.add_argument(
        "source",
        nargs="*",
        default=["-"],
        help=(
            "source text files, or - for standard input; several are read in "
            "order and separated, so no sentence spans two of them"
        ),
    )
    _add_console_arguments(extract)
    _add_language_arguments(extract)
    extract.add_argument(
        "--format", choices=("text", "json"), default="text", help="output format"
    )
    extract.add_argument(
        "--whole-index",
        action="store_true",
        help="parse every Wiktionary title, instead of only those the text could use",
    )

    define = subcommands.add_parser(
        "define", help="fetch definitions and build the glosses, and stop there"
    )
    _add_source_arguments(define)
    _add_definition_arguments(define)
    define.add_argument(
        "--format",
        choices=("text", "json", "markdown"),
        default="text",
        help="output format",
    )
    define.add_argument(
        "--out", help="write the output to this file instead of standard output"
    )

    deck = subcommands.add_parser(
        "deck", help="run the whole pipeline and write an Anki deck"
    )
    _add_source_arguments(deck)
    _add_definition_arguments(deck)
    deck.add_argument(
        "--format",
        choices=("apkg", "text", "json"),
        default="apkg",
        help="write an Anki package, or dump the cards for reading",
    )
    deck.add_argument(
        "--out",
        help="where to write the deck (default: the source's name, with .apkg)",
    )
    deck.add_argument(
        "--name", help="name of the deck inside Anki (default: the source's name)"
    )
    deck.add_argument(
        "--description",
        help=(
            "what the deck says it was built from (default: the source's name); "
            "Wiktionary's attribution is appended either way"
        ),
    )
    deck.add_argument(
        "--mother-lang",
        type=_language_code,
        default=SOURCE_LANG,
        help=(
            "language code to write the cards in, like --target-lang "
            f"(default: {SOURCE_LANG}, the edition's own, which needs no "
            "translation)"
        ),
    )
    deck.add_argument(
        "--no-translate",
        action="store_true",
        help="leave the cards in the edition's language whatever --mother-lang says",
    )
    deck.add_argument(
        "--seed",
        type=int,
        help="seed for the shuffle, so a deck can be built the same way twice",
    )
    deck.add_argument(
        "--window",
        type=int,
        default=shuffling.WINDOW,
        help=(
            "shuffle cards no further than this many places from where the source "
            f"put them (default: {shuffling.WINDOW}, a week of learning)"
        ),
    )

    index = subcommands.add_parser(
        "index", help="build the whole title index ahead of time"
    )
    _add_console_arguments(index)
    _add_language_arguments(index)

    arguments = parser.parse_args(argv)
    console.configure(getattr(arguments, "verbose", 0), getattr(arguments, "quiet", False))
    if getattr(arguments, "wiktionary_host", None):
        pages.HOST = arguments.wiktionary_host
    if arguments.command == "index":
        return _run_index(arguments)
    if arguments.command == "define":
        return _run_define(arguments)
    if arguments.command == "deck":
        return _run_deck(arguments)
    return _run_extract(arguments)


def _language_code(value: str) -> str:
    """A language code, checked while the flags are still being read.

    Both language flags take one. A code decker cannot name would reach the
    model as itself -- cards written for "a speaker of pt-" -- and, for the
    target language, would reach Stanza, which answers an unknown code with a
    `ValueError` and a traceback where decker should have said one line. The
    README promises the run is refused before it starts; this is what does it.
    """
    code = value.strip().casefold()
    if not languages.known(code):
        raise argparse.ArgumentTypeError(
            f"unknown language code {value!r}: a code is what both language flags "
            "take (en, es, pt, zh-hans...), not a name"
        )
    return code


def _add_console_arguments(parser: argparse.ArgumentParser) -> None:
    """How much the run says, and how loudly.

    Counted rather than named -- `-v`, `-vv` -- because the levels are ordered
    and nobody remembers what the third one is called. `--quiet` is the floor:
    what a run cannot continue past, and nothing else.
    """
    parser.add_argument(
        "-v",
        "--verbose",
        action="count",
        default=0,
        help="name each word as it is looked up; twice, each sentence and what "
        "the model was asked",
    )
    parser.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="print only what stops the run",
    )


def _add_language_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--target-lang",
        required=True,
        type=_language_code,
        help="language of the source text, as a language code (en, de, es...)",
    )
    parser.add_argument(
        "--edition",
        help="Wiktionary edition to take titles from (default: en, v1's mother language)",
    )
    parser.add_argument(
        "--refresh-titles",
        action="store_true",
        help="re-download the title dump even if it is already cached",
    )


def _add_source_arguments(parser: argparse.ArgumentParser) -> None:
    """The source text, its language, and how much of the index to build."""
    parser.add_argument(
        "source",
        nargs="*",
        default=["-"],
        help=(
            "source text files, or - for standard input; several are read in "
            "order and separated, so no sentence spans two of them"
        ),
    )
    _add_console_arguments(parser)
    _add_language_arguments(parser)
    parser.add_argument(
        "--whole-index",
        action="store_true",
        help="parse every Wiktionary title, instead of only those the text could use",
    )


def _add_definition_arguments(parser: argparse.ArgumentParser) -> None:
    """What definition fetching needs: a model, and what to do without one."""
    parser.add_argument(
        "--model",
        default=default_model(),
        help=(
            "ollama model used to choose senses and translate "
            f"(default: ${MODEL_VARIABLE}, else {DEFAULT_MODEL})"
        ),
    )
    parser.add_argument(
        "--ollama-host",
        help=f"ollama endpoint (default: $OLLAMA_HOST, else {DEFAULT_HOST})",
    )
    parser.add_argument(
        "--no-disambiguate",
        action="store_true",
        help="keep every sense of a page instead of asking the model to choose",
    )
    parser.add_argument(
        "--no-audio", action="store_true", help="do not download pronunciation files"
    )
    parser.add_argument(
        "--no-concepts",
        action="store_true",
        help=(
            "do not make cards for the grammatical terminology a definition uses "
            "(dative, diminutive, first person...)"
        ),
    )
    parser.add_argument(
        "--unknowns",
        choices=("off", "fix", "all"),
        default="fix",
        help=(
            "what to do with a word Wiktionary has no entry for: 'off' drops it, "
            "'fix' looks up a misspelling and teaches a foreign word the reader "
            "would not know, 'all' also teaches the foreign words they would"
        ),
    )
    parser.add_argument(
        "--teach-script",
        action="store_true",
        help=(
            "teach the writing system as well: every character a card displays "
            "that the mother tongue does not use -- letters, punctuation, IPA "
            "symbols -- gets a card of its own, ahead of the cards that show it"
        ),
    )
    parser.add_argument(
        "--no-rules",
        action="store_true",
        help=(
            "do not work out the morphological rules behind the inflected forms; "
            "every form keeps a card of its own"
        ),
    )
    parser.add_argument(
        "--wiktionary-host",
        metavar="ORIGIN",
        help=(
            "where to fetch pages from, e.g. http://localhost:8080 for a local "
            f"mirror (default: ${pages.HOST_VARIABLE}, else the edition's own host)"
        ),
    )
    parser.add_argument(
        "--refresh-answers",
        action="store_true",
        help="ask the model again instead of reusing answers it already gave",
    )
    parser.add_argument(
        "--previous",
        metavar="DECK.apkg",
        help=(
            "a deck built earlier: the glosses it already teaches are left out, "
            "so the run makes only what is new"
        ),
    )
    parser.add_argument(
        "--refresh-pages",
        action="store_true",
        help="re-fetch pages even if they are already cached",
    )


def _definition_arguments(arguments: argparse.Namespace) -> dict:
    """Those same arguments, as the pipeline's keywords."""
    return dict(
        edition=arguments.edition,
        whole_index=arguments.whole_index,
        refresh_titles=arguments.refresh_titles,
        model=arguments.model,
        host=arguments.ollama_host,
        disambiguate=not arguments.no_disambiguate,
        audio=not arguments.no_audio,
        concepts=not arguments.no_concepts,
        rules=not arguments.no_rules,
        teach_script=arguments.teach_script,
        unknowns=arguments.unknowns,
        refresh_pages=arguments.refresh_pages,
        refresh_answers=arguments.refresh_answers,
        known=_taught(arguments.previous),
    )


def _taught(previous: str | None) -> frozenset[str]:
    """What a previously built deck already teaches, or nothing."""
    if not previous:
        return frozenset()
    keys = anki.taught(previous)
    console.log(f"[decker] {len(keys)} glosses already taught by {Path(previous).name}")
    if not keys:
        console.log(
            "[decker] that deck records no gloss keys -- decks built before "
            "decker recorded them carry none, and every gloss will be made again",
            kind="warn",
        )
    return keys


#: What goes between two sources. A blank line, because that is what the
#: sentence splitter breaks on: `cat a.txt b.txt` runs the last sentence of one
#: into the first of the next -- `...se cortaba.El perro corrio...` -- and the
#: parser is handed a sentence nobody wrote. Two cue files concatenated have
#: the same problem one level down, their timings restarting mid-stream, so
#: each is folded on its own and the results are separated here.
SOURCE_SEPARATOR = "\n\n"


def _source_text(sources: list[str] | str) -> str:
    """Every source as one running text, whatever files they arrived in.

    Each is read by its own extension, so a `.srt` and a `.txt` can be given
    together, and they are joined by :data:`SOURCE_SEPARATOR`. The order is the
    order given: an episode at a time, and the deck teaches the earlier ones
    first, which is what the shuffle then paces.
    """
    if isinstance(sources, str):
        sources = [sources]
    text = SOURCE_SEPARATOR.join(_one_source(source).strip() for source in sources)
    console.log(
        f"[decker] read {len(sources)} source{'' if len(sources) == 1 else 's'}, "
        f"{len(text)} characters",
        kind="head",
    )
    return text


def _one_source(source: str) -> str:
    """One source as running text.

    The extension decides: `.srt` and `.vtt` are cue files and are folded back
    into prose by :mod:`decker.subtitles` before anything else sees them.
    Standard input has no extension to go by, so it is sniffed instead -- a
    timing line is unmistakable -- which also catches a cue file saved under
    the wrong name.
    """
    if source == "-":
        console.log("[decker] reading standard input", level=console.VERBOSE)
        raw = sys.stdin.read()
        return subtitles.text_of(raw) if subtitles.looks_like(raw) else raw
    path = Path(source)
    console.log(f"[decker] reading {path.name}", level=console.VERBOSE)
    raw = path.read_text(encoding="utf-8")
    if path.suffix.lower() not in subtitles.SUFFIXES:
        return raw
    text = subtitles.text_of(raw)
    console.log(
        f"[decker] {path.name}: {len(raw.splitlines())} lines of cues -> "
        f"{len(text)} characters"
    )
    return text


def _run_extract(arguments: argparse.Namespace) -> int:
    sentences = pipeline.run(
        _source_text(arguments.source),
        target_lang=arguments.target_lang,
        edition=arguments.edition,
        whole_index=arguments.whole_index,
        refresh_titles=arguments.refresh_titles,
    )
    if arguments.format == "json":
        json.dump(
            [dataclasses.asdict(sentence) for sentence in sentences],
            sys.stdout,
            ensure_ascii=False,
            indent=2,
        )
        sys.stdout.write("\n")
    else:
        for sentence in sentences:
            print(sentence.text)
            for term in sentence.terms:
                others = [entry for entry in term.entries if entry != term.surface]
                marker = f"  -> {', '.join(others)}" if others else ""
                print(f"    {term.surface}{marker}")
            print()
    return 0


def _run_define(arguments: argparse.Namespace) -> int:
    glosses = pipeline.define(
        _source_text(arguments.source),
        target_lang=arguments.target_lang,
        **_definition_arguments(arguments),
    )
    if arguments.format == "json":
        rendered = (
            json.dumps(
                [dataclasses.asdict(gloss) for gloss in glosses],
                ensure_ascii=False,
                indent=2,
            )
            + "\n"
        )
    elif arguments.format == "markdown":
        rendered = markdown.render(
            glosses,
            title=_document_title(arguments.source),
            edition=arguments.edition or pipeline.MOTHER_EDITION,
        )
    else:
        rendered = "".join(_format_gloss(gloss) for gloss in glosses)

    if arguments.out:
        Path(arguments.out).write_text(rendered, encoding="utf-8")
        console.log(f"[decker] wrote {arguments.out}", kind="head")
    else:
        sys.stdout.write(rendered)
    return 0


def _run_deck(arguments: argparse.Namespace) -> int:
    cards = pipeline.deck(
        _source_text(arguments.source),
        target_lang=arguments.target_lang,
        mother_lang=arguments.mother_lang,
        translate=not arguments.no_translate,
        seed=arguments.seed,
        window=arguments.window,
        **_definition_arguments(arguments),
    )
    name = arguments.name or _document_title(arguments.source)

    if arguments.format == "apkg":
        out = Path(arguments.out or f"{_document_stem(arguments.source)}.apkg")
        anki.write(
            cards,
            out,
            name=name,
            source=_document_title(arguments.source),
            description=arguments.description,
            edition=arguments.edition or pipeline.MOTHER_EDITION,
        )
        console.log(f"[decker] wrote {out}", kind="head")
        return 0

    if arguments.format == "json":
        rendered = (
            json.dumps(
                [dataclasses.asdict(card) for card in cards],
                ensure_ascii=False,
                indent=2,
            )
            + "\n"
        )
    else:
        rendered = "".join(
            _format_card(card, position)
            for position, card in enumerate(cards, start=1)
        )

    if arguments.out:
        Path(arguments.out).write_text(rendered, encoding="utf-8")
        console.log(f"[decker] wrote {arguments.out}", kind="head")
    else:
        sys.stdout.write(rendered)
    return 0


def _format_card(card, position: int) -> str:
    """One card as a few lines, in the order it is to be studied."""
    heading = f"{position}. [{card.kind}] card {card.index}, gloss {card.gloss}"
    if card.depends_on:
        heading += f"  after {', '.join(str(index) for index in card.depends_on)}"
    lines = [heading]
    lines += [f"    ? {piece}" for piece in _side(card.challenge)]
    lines += [f"    = {piece}" for piece in _side(card.answer)]
    return "\n".join(lines) + "\n\n"


def _side(side) -> list[str]:
    pieces = []
    if side.term:
        pieces.append(side.term)
    if side.definition:
        pieces.append(side.definition)
    if side.headword:
        pieces.append(side.headword)
    pieces += [str(example) for example in side.examples]
    pieces += list(side.renderings)
    if side.ipa:
        pieces.append(" ".join(side.ipa))
    if side.etymology:
        pieces.append(side.etymology)
    pieces += [Path(audio).name for audio in side.audios]
    return pieces


def _document_stem(sources: list[str] | str) -> str:
    """What the deck file is called when `--out` does not say.

    Several sources name the file after the first and say how many followed --
    `ep01+2.apkg`. Naming it `ep01.apkg` would be the obvious thing and the
    wrong one: a deck built from three episodes would silently overwrite the
    deck built from the first, and `--out` overwrites without asking.
    """
    sources = [sources] if isinstance(sources, str) else sources
    first = "deck" if sources[0] == "-" else Path(sources[0]).stem
    return first if len(sources) == 1 else f"{first}+{len(sources) - 1}"


def _document_title(sources: list[str] | str) -> str:
    """What the deck is called inside Anki, and what a document credits."""
    sources = [sources] if isinstance(sources, str) else sources
    def named(source: str) -> str:
        return "Standard input" if source == "-" else Path(source).stem

    if len(sources) == 1:
        return named(sources[0])
    if len(sources) == 2:
        return f"{named(sources[0])} and {named(sources[1])}"
    return f"{named(sources[0])} and {len(sources) - 1} more"


def _format_gloss(gloss) -> str:
    heading = f"{gloss.index}. {gloss.surface}"
    if gloss.lemma != gloss.surface:
        heading += f"  [{gloss.lemma}]"
    if gloss.entry not in (gloss.surface, gloss.lemma):
        heading += f"  <{gloss.entry}>"
    if gloss.depends_on:
        heading += f"  after {', '.join(str(index) for index in gloss.depends_on)}"
    lines = [heading]
    if gloss.ipa:
        lines.append(f"    {' '.join(gloss.ipa)}")
    lines.append(f"    - {gloss.definition}")
    lines += [f"      · {example}" for example in gloss.examples]
    if gloss.etymology:
        lines.append(f"    etymology: {gloss.etymology}")
    lines += [f"    audio: {audio}" for audio in gloss.audios]
    return "\n".join(lines) + "\n\n"


def _run_index(arguments: argparse.Namespace) -> int:
    index = pipeline.build_index(
        arguments.target_lang,
        edition=arguments.edition,
        refresh_titles=arguments.refresh_titles,
    )
    console.log(
        f"[decker] indexed {len(index.words)} single-word titles and "
        f"{sum(len(entries) for entries in index.phrases.values())} phrases",
        kind="head",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

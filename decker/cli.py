"""Command line entry point for the v1 pipeline."""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from pathlib import Path

from decker import anki, languages, markdown, pipeline, shuffling
from decker.ollama import DEFAULT_HOST, DEFAULT_MODEL, MODEL_VARIABLE, default_model
from decker.translation import SOURCE_LANG

#: Every stage runs in one go; the subcommands below stop the pipeline early.
DEFAULT_COMMAND = "deck"
COMMANDS = ("extract", "define", "deck", "index")


def main(argv: list[str] | None = None) -> int:
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
    )
    subcommands = parser.add_subparsers(dest="command", required=True)

    extract = subcommands.add_parser(
        "extract", help="extract the terms of a source text and stop there"
    )
    extract.add_argument(
        "source",
        nargs="?",
        default="-",
        help="source text file, or - for standard input",
    )
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
    _add_language_arguments(index)

    arguments = parser.parse_args(argv)
    if arguments.command == "index":
        return _run_index(arguments)
    if arguments.command == "define":
        return _run_define(arguments)
    if arguments.command == "deck":
        return _run_deck(arguments)
    return _run_extract(arguments)


def _language_code(value: str) -> str:
    """A language code, checked while the flags are still being read.

    A code decker cannot name would reach the model as itself -- cards written
    for "a speaker of pt-", which is worse than a run that never starts.
    """
    code = value.strip().casefold()
    if not languages.known(code):
        raise argparse.ArgumentTypeError(
            f"unknown language code {value!r}: --mother-lang takes a code, the way "
            "--target-lang does (en, es, pt...)"
        )
    return code


def _add_language_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--target-lang",
        required=True,
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
        nargs="?",
        default="-",
        help="source text file, or - for standard input",
    )
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
        refresh_pages=arguments.refresh_pages,
    )


def _source_text(source: str) -> str:
    if source == "-":
        return sys.stdin.read()
    return Path(source).read_text(encoding="utf-8")


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
        print(f"[decker] wrote {arguments.out}", file=sys.stderr)
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
        print(f"[decker] wrote {out}", file=sys.stderr)
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
        print(f"[decker] wrote {arguments.out}", file=sys.stderr)
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
    pieces += [str(example) for example in side.examples]
    if side.ipa:
        pieces.append(" ".join(side.ipa))
    if side.etymology:
        pieces.append(side.etymology)
    pieces += [Path(audio).name for audio in side.audios]
    return pieces


def _document_stem(source: str) -> str:
    return "deck" if source == "-" else Path(source).stem


def _document_title(source: str) -> str:
    return "Standard input" if source == "-" else Path(source).stem


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
    print(
        f"[decker] indexed {len(index.words)} single-word titles and "
        f"{sum(len(entries) for entries in index.phrases.values())} phrases",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Command line entry point for the v1 pipeline."""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from pathlib import Path

from decker import markdown, pipeline
from decker.disambiguation import DEFAULT_HOST, DEFAULT_MODEL

#: Every stage runs in one go; the subcommands below stop the pipeline early.
DEFAULT_COMMAND = "define"
COMMANDS = ("extract", "define", "index")


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or (argv[0] not in COMMANDS and argv[0] not in ("-h", "--help")):
        argv.insert(0, DEFAULT_COMMAND)

    parser = argparse.ArgumentParser(
        prog="decker",
        description=(
            "Build language-learning material from a text. With no subcommand the "
            "whole pipeline runs, which is what `define` does; `extract` and `index` "
            "stop it early."
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
        "define", help="fetch definitions and build the glosses of a source text"
    )
    define.add_argument(
        "source",
        nargs="?",
        default="-",
        help="source text file, or - for standard input",
    )
    _add_language_arguments(define)
    define.add_argument(
        "--format",
        choices=("text", "json", "markdown"),
        default="text",
        help="output format",
    )
    define.add_argument(
        "--out", help="write the output to this file instead of standard output"
    )
    define.add_argument(
        "--whole-index",
        action="store_true",
        help="parse every Wiktionary title, instead of only those the text could use",
    )
    define.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help=f"ollama model used for sense disambiguation (default: {DEFAULT_MODEL})",
    )
    define.add_argument(
        "--ollama-host",
        help=f"ollama endpoint (default: $OLLAMA_HOST, else {DEFAULT_HOST})",
    )
    define.add_argument(
        "--no-disambiguate",
        action="store_true",
        help="keep every sense of a page instead of asking the model to choose",
    )
    define.add_argument(
        "--no-audio", action="store_true", help="do not download pronunciation files"
    )
    define.add_argument(
        "--refresh-pages",
        action="store_true",
        help="re-fetch pages even if they are already cached",
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
    return _run_extract(arguments)


def _add_language_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--target-lang",
        required=True,
        help="language of the source text, as a Stanza language code (en, de, es...)",
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
        edition=arguments.edition,
        whole_index=arguments.whole_index,
        refresh_titles=arguments.refresh_titles,
        model=arguments.model,
        host=arguments.ollama_host,
        disambiguate=not arguments.no_disambiguate,
        audio=not arguments.no_audio,
        refresh_pages=arguments.refresh_pages,
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
    if gloss.audio:
        lines.append(f"    audio: {gloss.audio}")
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

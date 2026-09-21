"""Command line entry point for the v1 pipeline."""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from pathlib import Path

from decker import (
    anki, console, languages, manga, markdown, pages, pipeline, script,
    shuffling, subtitles, timeline,
)
from decker.wiktionary import USER_AGENT
from decker.ollama import DEFAULT_HOST, DEFAULT_MODEL, MODEL_VARIABLE, default_model
from decker.translation import SOURCE_LANG

#: Every stage runs in one go; the subcommands below stop the pipeline early.
DEFAULT_COMMAND = "deck"
COMMANDS = ("extract", "define", "deck", "index", "timeline")


def main(argv: list[str] | None = None) -> int:
    try:
        return _main(argv)
    except anki.Unreadable as unreadable:
        #: Before anything was built, since both flags that read a deck read
        #: it first: the run has cost nothing yet and the message is the
        #: whole of what the user needs.
        console.log(f"[decker] {unreadable}", level=console.QUIET, kind="error")
        return 2
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
            "`index` stop it early, and `timeline` reads a deck back against the "
            "subtitle file it was built from."
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
        "--update",
        metavar="DECK.apkg",
        help=(
            "a deck already imported into Anki: the cards it holds keep the "
            "identity they have there, so importing this one corrects them in "
            "place -- their scheduling included -- instead of adding a second "
            "copy beside each"
        ),
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

    timing = subcommands.add_parser(
        "timeline",
        help=(
            "say how far into a deck a viewer must be to have met every word "
            "said up to each timestamp of a subtitle file"
        ),
    )
    timing.add_argument(
        "source",
        nargs="?",
        default="-",
        help="a subtitle file -- .srt or .vtt -- or - for standard input",
    )
    timing.add_argument(
        "--deck",
        required=True,
        metavar="DECK.apkg",
        help=(
            "the deck to measure against: one built from this file, or exported "
            "from Anki after studying it, which also counts what is behind you"
        ),
    )
    timing.add_argument(
        "--every",
        type=int,
        default=timeline.EVERY,
        metavar="SECONDS",
        help=f"how much of the file one row covers (default: {timeline.EVERY})",
    )
    timing.add_argument(
        "--rate",
        type=int,
        default=timeline.RATE,
        metavar="CARDS",
        help=(
            "new cards a day, for turning a position in the deck into days "
            f"(default: {timeline.RATE}, which is Anki's own)"
        ),
    )
    timing.add_argument(
        "--cover",
        type=float,
        default=timeline.COVER,
        metavar="SHARE",
        help=(
            "the share of a stretch's words the headline figure teaches "
            f"(default: {timeline.COVER}; 1 asks for all of them, which the "
            "furthest column reports anyway)"
        ),
    )
    timing.add_argument(
        "--format", choices=("text", "csv", "json"), default="text",
        help="output format",
    )
    timing.add_argument(
        "--out", help="write the output to this file instead of standard output"
    )
    _add_console_arguments(timing)
    _add_language_arguments(timing)
    timing.add_argument(
        "--whole-index",
        action="store_true",
        help="parse every Wiktionary title, instead of only those the text could use",
    )
    _add_definition_arguments(timing)

    index = subcommands.add_parser(
        "index", help="build the whole title index ahead of time"
    )
    _add_console_arguments(index)
    _add_language_arguments(index)

    arguments = parser.parse_args(argv)
    console.configure(
        getattr(arguments, "verbose", 0),
        getattr(arguments, "quiet", False),
        screen=not getattr(arguments, "no_screen", False),
    )
    console.console.headline = _headline(arguments)
    if getattr(arguments, "wiktionary_host", None):
        pages.HOST = arguments.wiktionary_host
    #: Before the screen, and so before any of the work: the source is what
    #: says whether the reader can read it, and a question is asked of a
    #: terminal decker still has -- under the screen it would be a modal
    #: drawn over a dashboard, and an hour into the run it would be a
    #: question about work already done. The two lines it costs above the
    #: screen are the reading of the source, which is where they belong.
    text = None
    if arguments.command in ("extract", "define", "deck"):
        text = _source_text(arguments.source)
        if arguments.command in ("define", "deck"):
            arguments.teach_script = _script_taught(arguments, text)

    #: The whole run happens under the screen, including the part that writes
    #: the output: what a subcommand prints to stdout is held until the screen
    #: is down and let go afterwards, so `--format text` on a terminal reads
    #: the same as it always did.
    with console.console.watching():
        if arguments.command == "index":
            return _run_index(arguments)
        if arguments.command == "define":
            return _run_define(arguments, text)
        if arguments.command == "deck":
            return _run_deck(arguments, text)
        if arguments.command == "timeline":
            return _run_timeline(arguments)
        return _run_extract(arguments, text)


def _headline(arguments: argparse.Namespace) -> str:
    """What this run is, in a line, for the top of the screen.

    The three things that decide what comes out and are not visible from the
    log: which languages, which model, and which source. A screenshot of a run
    is otherwise a screenshot of any run.
    """
    parts = []
    if getattr(arguments, "target_lang", None):
        parts.append(f"{arguments.target_lang} → "
                     f"{getattr(arguments, 'mother_lang', SOURCE_LANG)}")
    if getattr(arguments, "model", None) or getattr(arguments, "source", None):
        parts.append(getattr(arguments, "model", None) or default_model())
    if getattr(arguments, "source", None):
        parts.append(_document_title(arguments.source))
    return " · ".join(parts)


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
    parser.add_argument(
        "--no-screen",
        action="store_true",
        help="plain lines and a one-line bar, instead of the log-and-tally "
        "screen a terminal otherwise gets",
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
        "--no-components",
        action="store_true",
        help=(
            "do not make cards for the terms an etymology decomposes a word "
            "into (des- + cargar, veneno + -oso), recursively"
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
        #: Neither on nor off until the run has seen the text: with no flag
        #: at all, a source written in a script the reader cannot read asks
        #: (:func:`_script_taught`). Saying no to that question is a thing a
        #: run has to be able to say in advance, which is `--no-teach-script`.
        default=None,
        help=(
            "teach the writing system as well: every character a card displays "
            "that the mother tongue does not use -- letters, punctuation, IPA "
            "symbols -- gets a card of its own, ahead of the cards that show it "
            "(asked about, on a terminal, when the source turns out to be "
            "written in one)"
        ),
    )
    parser.add_argument(
        "--no-teach-script",
        dest="teach_script",
        action="store_false",
        help="do not teach the writing system, and do not ask about it",
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
        components=not arguments.no_components,
        rules=not arguments.no_rules,
        teach_script=bool(arguments.teach_script),
        limit_glosses=arguments.limit_glosses,
        unknowns=arguments.unknowns,
        refresh_pages=arguments.refresh_pages,
        refresh_answers=arguments.refresh_answers,
        known=_taught(arguments.previous),
    )


def _script_taught(arguments: argparse.Namespace, text: str) -> bool:
    """Whether to teach the writing system, asking where the flag is silent.

    `--teach-script` is off by default and always has been, and a default-off
    flag is only ever used by someone who already knows it exists. The one
    run that needs it is also the one run that announces itself: a source
    written in a script the reader cannot read is visible in the text before
    a word of it has been looked up. So with neither flag given, the reader's
    scripts known and the text mostly standing in others, the question is put
    once -- and `--no-teach-script` is there for the run that wants it never
    asked. Bru's todo of 2026-09-21.

    Answered no wherever it cannot be asked: no terminal, `-q`, or the source
    arriving on standard input, which is the descriptor the answer would have
    to come from. A run that cannot be asked is told instead, in one line, so
    a pipeline's log says which flag it was missing.

    Nothing here overrides a flag: `--teach-script` and `--no-teach-script`
    are answers given in advance, and a run that gave one is never asked.
    """
    if arguments.teach_script is not None:
        return arguments.teach_script
    mother = getattr(arguments, "mother_lang", SOURCE_LANG)
    reads = script.scripts_of(mother)
    #: The same unknown the stage itself stands down on: decker knows which
    #: scripts a reader of English reads and no more, and a question it
    #: cannot ask honestly is not asked.
    if reads is None:
        return False
    unreadable = script.unreadable(text, reads)
    if not unreadable:
        return False
    written = _listed([script.name_of(one) for one in unreadable])
    said = (
        f"[decker] this text is written in {written}, which a reader of "
        f"{languages.name_of(mother)} does not read"
    )
    if not _may_ask(arguments):
        console.log(
            f"{said}; --teach-script would teach those characters themselves, "
            "a pair of cards each, ahead of the words that use them",
            kind="warn",
        )
        return False
    console.log(said, kind="head")
    return _yes(
        "[decker] teach those characters themselves, a pair of cards each? [y/N] "
    )


def _may_ask(arguments: argparse.Namespace) -> bool:
    """Whether this run has a person on the other end of it to ask.

    A terminal at both ends, and standard input still being a terminal rather
    than the document: `decker - < episode.txt` has already spent the
    descriptor an answer would come from.
    """
    sources = arguments.source
    if "-" in ([sources] if isinstance(sources, str) else sources):
        return False
    if not (sys.stdin and sys.stdin.isatty()):
        return False
    return console.console.interactive and console.console.level > console.QUIET


def _yes(question: str) -> bool:
    """Ask, and take anything but a plain yes as no.

    An interrupted or closed prompt is a no as well: the flag adds cards, and
    a run that was never answered should build the deck it would have built
    without the question.
    """
    try:
        answer = input(question)
    except (EOFError, KeyboardInterrupt):
        print()
        return False
    return answer.strip().casefold() in ("y", "yes")


def _listed(names: list[str]) -> str:
    """`Hiragana, Han and Katakana`: a list as a line of prose says it."""
    if len(names) < 3:
        return " and ".join(names)
    return f"{', '.join(names[:-1])} and {names[-1]}"


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


def _queued_after(previous: str | None) -> int:
    """Where a deck's cards start, given the deck they are being added to.

    Only with `--previous`, which is what says this deck is an addition
    rather than a rebuild: its cards are the ones that deck does not teach,
    so they belong behind whatever it has left to show. A rebuild is numbered
    from 1, since every card of it is in the list and the list is the order.
    """
    if not previous:
        return 0
    last = anki.last_position(previous)
    if last:
        console.log(
            f"[decker] numbering these cards from {last + 1}, after the "
            f"{last} {Path(previous).name} has not shown yet"
        )
    return last


def _identities(update: str | None) -> dict[tuple[str, str], str]:
    """The note ids a deck already in Anki gave the cards it holds."""
    if not update:
        return {}
    found = anki.identities(update)
    console.log(
        f"[decker] {len(found)} notes of {Path(update).name} keep their "
        "identity, so importing this deck corrects them in place"
    )
    if not found:
        console.log(
            "[decker] that deck records no gloss keys -- decks built before "
            "decker recorded them carry none, and nothing can be matched to "
            "them; its cards will be added again rather than corrected",
            kind="warn",
        )
    return found


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
    into prose by :mod:`decker.subtitles`, `.mbz` and `.mbz.zip` are OCR'd
    manga volumes and are folded by :mod:`decker.manga`, before anything else
    sees them. Standard input has no extension to go by, so it is sniffed
    instead -- a timing line is unmistakable -- which also catches a cue file
    saved under the wrong name. A manga archive is a zip and cannot arrive
    that way, so nothing sniffs for one.
    """
    if source == "-":
        console.log("[decker] reading standard input", level=console.VERBOSE)
        raw = sys.stdin.read()
        return subtitles.text_of(raw) if subtitles.looks_like(raw) else raw
    path = Path(source)
    console.log(f"[decker] reading {path.name}", level=console.VERBOSE)
    if manga.looks_like(source):
        return _manga_text(source, path)
    raw = path.read_text(encoding="utf-8")
    if path.suffix.lower() not in subtitles.SUFFIXES:
        return raw
    text = subtitles.text_of(raw)
    console.log(
        f"[decker] {path.name}: {len(raw.splitlines())} lines of cues -> "
        f"{len(text)} characters"
    )
    return text


def _manga_text(source: str, path: Path) -> str:
    """A mokuro volume as prose, and the line that says how much of it there was.

    The count is of *bubbles*, not of pages: a page of a comic can be silent,
    and a run that says how many pages it read would claim more text than it
    has. What reaches the pipeline is one paragraph per bubble.
    """
    text = manga.text_of(source)
    bubbles = text.count("\n\n") + 1 if text else 0
    console.log(
        f"[decker] {path.name}: {bubbles} speech bubbles -> {len(text)} characters"
    )
    return text


def _run_extract(arguments: argparse.Namespace, text: str) -> int:
    sentences = pipeline.run(
        text,
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


def _run_define(arguments: argparse.Namespace, text: str) -> int:
    glosses = pipeline.define(
        text,
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


def _run_deck(arguments: argparse.Namespace, text: str) -> int:
    #: Read before the pipeline, not at the write: a deck decker cannot read
    #: is worth saying so about now rather than after an hour of fetching.
    keeping = _identities(getattr(arguments, "update", None))
    cards = pipeline.deck(
        text,
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
            #: A deck built to be *added* to one being studied is numbered
            #: after it; a deck built to *replace* one is numbered as itself,
            #: because its own order is the order the whole deck wants.
            after=_queued_after(arguments.previous),
            keeping=keeping,
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
    if side.equivalent:
        pieces.append(side.equivalent)
    if side.definition:
        pieces.append(side.definition)
    if side.headword:
        pieces.append(side.headword)
    pieces += [str(example) for example in side.examples]
    pieces += list(side.renderings)
    if side.ipa:
        pieces.append(" ".join(side.ipa))
    pieces += list(side.readings)
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
    first = "deck" if sources[0] == "-" else _stem(Path(sources[0]))
    return first if len(sources) == 1 else f"{first}+{len(sources) - 1}"


def _stem(path: Path) -> str:
    """The file's name without what says which format it is in.

    `Path.stem` takes one suffix off, which is right for `ep01.srt` and wrong
    for `0001.mbz.zip`: that leaves `0001.mbz`, and the deck is written to
    `0001.mbz.apkg`. A double extension is the archive's own convention -- the
    zip of a `.mbz` -- so both come off.
    """
    stem = path.stem
    return Path(stem).stem if Path(stem).suffix.lower() in manga.SUFFIXES else stem


def _document_title(sources: list[str] | str) -> str:
    """What the deck is called inside Anki, and what a document credits."""
    sources = [sources] if isinstance(sources, str) else sources
    def named(source: str) -> str:
        """The source's own name for itself, falling back to the file's.

        A manga archive is named after its volume number and nothing else --
        `0001.mbz.zip` -- so a deck named after the file is called `0001` in a
        collection that will hold next month's `0001` too. The archive's
        metadata knows the series; the *filename* still comes from the file,
        that being where the user said to put it.
        """
        if source == "-":
            return "Standard input"
        own = manga.title_of(source) if manga.looks_like(source) else ""
        return own or _stem(Path(source))

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
    lines += [f"    {reading}" for reading in gloss.readings]
    lines.append(f"    - {gloss.definition}")
    lines += [f"      · {example}" for example in gloss.examples]
    if gloss.etymology:
        lines.append(f"    etymology: {gloss.etymology}")
    lines += [f"    audio: {audio}" for audio in gloss.audios]
    return "\n".join(lines) + "\n\n"


def _run_timeline(arguments: argparse.Namespace) -> int:
    """Measure one cue file against a deck built from it."""
    source = arguments.source
    raw = sys.stdin.read() if source == "-" else Path(source).read_text(encoding="utf-8")
    if not subtitles.looks_like(raw):
        #: By its contents and not by its name: the point of the command is
        #: the clock, and a file without one has nothing to measure. Said
        #: plainly, because the obvious mistake is passing the `.txt` the deck
        #: was also built from.
        console.log(
            f"[decker] {'standard input' if source == '-' else source} carries no "
            "cue timings, so there is nothing to place on a clock; a timeline "
            "needs the .srt or .vtt itself",
            level=console.QUIET, kind="error",
        )
        return 2
    cues = subtitles.timed(raw)
    text = subtitles.text_of(raw)
    if not cues:
        #: A header and timing lines but nothing said under them: a file
        #: decker can read and has nothing to place. Same exit as the file
        #: with no clock at all, since neither can be measured.
        console.log(
            f"[decker] {'standard input' if source == '-' else source} has cue "
            "timings but no words under them, so there is nothing to place",
            level=console.QUIET, kind="error",
        )
        return 2
    console.log(
        f"[decker] {len(cues)} cues -> {len(text)} characters, "
        f"{timeline.clock(max(placed.cue.end for placed in cues))} of subtitles",
        kind="head",
    )
    sentences, glosses = pipeline.glossed(
        text, target_lang=arguments.target_lang, **_definition_arguments(arguments)
    )
    deck = anki.placed(arguments.deck)
    rows = timeline.measure(
        glosses,
        sentences,
        cues,
        deck,
        every=arguments.every,
        rate=arguments.rate,
        cover=arguments.cover,
    )
    timeline.report(rows, glosses, deck)

    if arguments.format == "json":
        rendered = (
            json.dumps(
                [dataclasses.asdict(row) for row in rows], ensure_ascii=False, indent=2
            )
            + "\n"
        )
    elif arguments.format == "csv":
        rendered = "".join(
            [
                "time,seconds,cues,glosses,untaught,cards,days,furthest,"
                "furthest_days\n",
                *(
                    f"{timeline.clock(row.at)},{row.at:.1f},{row.cues},"
                    f"{row.glosses},{row.untaught},"
                    f"{'' if row.cards is None else row.cards},"
                    f"{'' if row.days is None else format(row.days, '.1f')},"
                    f"{row.furthest},{row.furthest_days:.1f}\n"
                    for row in rows
                ),
            ]
        )
    else:
        rendered = _format_timeline(
            rows, rate=arguments.rate, cover=arguments.cover
        )

    if arguments.out:
        Path(arguments.out).write_text(rendered, encoding="utf-8")
        console.log(f"[decker] wrote {arguments.out}", kind="head")
    else:
        sys.stdout.write(rendered)
    return 0


def _format_timeline(rows: list, *, rate: int, cover: float) -> str:
    """The rows as a table, one line per stretch of the file.

    Read across: by this timestamp the file has said this many words, of
    which this many are in no card of the deck; to have been taught the share
    asked for you must be this far into the deck, which is this many days at
    your rate; and the last of that stretch's words sits this much further in.
    """
    share = f"{cover:.0%}"
    lines = [
        f"    up to    cues   words  no card  {share:>5} by   days      all by   days",
        "-" * 72,
    ]
    for row in rows:
        cards = "     --" if row.cards is None else f"{row.cards:>7}"
        days = "     --" if row.days is None else f"{row.days:>7.1f}"
        lines.append(
            f" {timeline.clock(row.at):>8}  {row.cues:>6}  {row.glosses:>6}  "
            f"{row.untaught:>7}  {cards}  {days}  {row.furthest:>10}  "
            f"{row.furthest_days:>7.1f}"
        )
    if rows and any(row.cards is None for row in rows):
        lines += [
            "",
            f"-- means the deck teaches too little of that stretch for {share} "
            "of it to be reachable at all.",
        ]
    return "\n".join(lines) + "\n"


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

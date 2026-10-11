"""Score one model on the known-answer checks in `checks.json`.

    OLLAMA_HOST=... DECKER_WIKTIONARY_HOST=... \
        uv run python tools/benchmark/run.py gemma4:latest out.json

What it measures is sense disambiguation and nothing else: for each language it
runs the pipeline over that language's sentences -- concepts and rules off, so
the glosses are word senses -- and asks of each check whether the senses kept
for one surface say what a reader of the passage would say, and do not say what
they would not. A check that names an occurrence with `at` is scored on the
senses kept for that occurrence alone, read off the question that was asked
about it.

Three outcomes, not two. A check whose term was never glossed is **absent**
rather than failed: it says nothing about the model, and it says quite a lot
about the run, since a benchmark whose terms stop being extracted is measuring
nothing. Term extraction changing under it is exactly the failure this has to
be able to report.

Each language has sixteen sentences: eight of Wikipedia lead text, CC BY-SA
4.0, from the articles its block names, and eight written for the benchmark to
be hard -- a context that settles a word whose first or commonest sense is the
wrong one -- and kept because they split the models measured. The method is in
`docs/execution/benchmark.md`.
"""

from __future__ import annotations

import io
import json
import os
import sys
import time
from contextlib import redirect_stderr
from pathlib import Path

from decker import disambiguation, pages, pipeline
from decker import glosses as G

HERE = Path(__file__).parent

#: Every sense question of the run, as (surface, passage, kept definitions). A
#: passage marks the occurrence it asks about -- `保存食⟨で⟩あった` -- which is
#: how a check with `at` is scored on one occurrence rather than on every
#: sense its surface kept anywhere in the block: `で` the copula and `で` *by
#: means of* can sit in the same block, and a gloss does not say where it was
#: met.
_ASKED: list[tuple[str, str, list[str]]] = []
_keep = disambiguation.Disambiguator.keep


def _recorded(self, senses, **kwargs):
    kept = _keep(self, senses, **kwargs)
    _ASKED.append((kwargs["surface"], kwargs["sentence"], [s.definition for s in kept]))
    return kept


disambiguation.Disambiguator.keep = _recorded


def main(model: str, out: str | None, refresh: bool = False) -> int:
    if "DECKER_WIKTIONARY_HOST" in os.environ:
        pages.HOST = os.environ["DECKER_WIKTIONARY_HOST"]
    bench = json.loads((HERE / "checks.json").read_text(encoding="utf-8"))["languages"]

    results: dict[str, dict] = {}
    started = time.time()
    for key, block in bench.items():
        text = " ".join(block["sentences"])
        _ASKED.clear()
        #: The run's own reporting is not the measurement, and it is long.
        with redirect_stderr(io.StringIO()):
            sentences = pipeline.run(text, target_lang=block["lang"], edition="en")
            built = G.build(
                sentences, target_lang=block["lang"], edition="en", model=model,
                host=os.environ.get("OLLAMA_HOST"), disambiguate=True, audio=False,
                concepts=False, components=False, rules=False, refresh_answers=refresh,
            )
        #: Folded, because a card is fronted with Wiktionary's spelling: a
        #: sentence-initial `Хозяин` is glossed `хозяин`, and a check written
        #: from the text would never find it.
        kept: dict[str, list[str]] = {}
        for gloss in built:
            kept.setdefault(gloss.surface.casefold(), []).append(gloss.definition)

        outcomes = []
        for check in block["checks"]:
            if "at" in check:
                asked = [kept for surface, passage, kept in _ASKED
                         if surface == check["surface"] and check["at"] in passage]
                senses = [d for kept in asked for d in kept] if asked else None
            else:
                senses = kept.get(check["surface"].casefold())
            if senses is None:
                outcomes.append(("absent", check["surface"], check["why"], ""))
                continue
            joined = " | ".join(senses).lower()
            wrong = any(w.lower() in joined for w in check["must_not"])
            missing = check["must"] and not any(m.lower() in joined for m in check["must"])
            state = "fail" if wrong or missing else "pass"
            shown = " | ".join(senses)[:110] if state == "fail" else ""
            outcomes.append((state, check["surface"], check["why"], shown))
        results[key] = {"glosses": len(built), "outcomes": outcomes}

    counted = [state for row in results.values() for state, *_ in row["outcomes"]]
    summary = {
        "model": model,
        "refreshed": refresh,
        "passed": counted.count("pass"),
        "failed": counted.count("fail"),
        "absent": counted.count("absent"),
        "glosses": sum(row["glosses"] for row in results.values()),
        "seconds": round(time.time() - started, 1),
        "languages": results,
    }
    print(f"{model}: {summary['passed']} passed, {summary['failed']} failed, "
          f"{summary['absent']} absent; {summary['glosses']} glosses, "
          f"{summary['seconds']:.0f}s{' (cold)' if refresh else ''}")
    for key, row in results.items():
        marks = " ".join(f"{state[0].upper()}:{surface}"
                         for state, surface, _, _ in row["outcomes"])
        print(f"   {key}: {row['glosses']:3d} glosses  {marks}")
    for key, row in results.items():
        for state, surface, why, shown in row["outcomes"]:
            if state != "pass":
                print(f"   {state.upper()} [{key}] {surface} -- {why}")
                if shown:
                    print(f"        kept: {shown}")
    if out:
        Path(out).write_text(json.dumps(summary, ensure_ascii=False, indent=1),
                             encoding="utf-8")
    return 0 if summary["failed"] == 0 else 1


if __name__ == "__main__":
    #: `--refresh` asks the model again for every answer it has on disk. The
    #: checks do not need it -- an answer is a pure function of the prompt at
    #: temperature zero -- but a *timing* does: a model that has run this
    #: before finishes in a tenth of the time and the number means nothing.
    arguments = [a for a in sys.argv[1:] if a != "--refresh"]
    if not arguments:
        sys.exit(__doc__)
    sys.exit(main(arguments[0], arguments[1] if len(arguments) > 1 else None,
                  refresh="--refresh" in sys.argv))

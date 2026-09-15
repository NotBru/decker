"""Score one model on the known-answer checks in `checks.json`.

    OLLAMA_HOST=... DECKER_WIKTIONARY_HOST=... \
        uv run python tools/benchmark/run.py gemma4:latest out.json

What it measures is sense disambiguation and nothing else: for each language it
runs the pipeline over that language's sentences -- concepts and rules off, so
the glosses are word senses -- and asks of each check whether the senses kept
for one surface say what a reader of the passage would say, and do not say what
they would not.

Three outcomes, not two. A check whose term was never glossed is **absent**
rather than failed: it says nothing about the model, and it says quite a lot
about the run, since a benchmark whose terms stop being extracted is measuring
nothing. Term extraction changing under it is exactly the failure this has to
be able to report.

The sentences are Wikipedia lead text, CC BY-SA 4.0, and each language block
names the articles it came from.
"""

from __future__ import annotations

import io
import json
import os
import sys
import time
from contextlib import redirect_stderr
from pathlib import Path

from decker import glosses as G
from decker import pages, pipeline

HERE = Path(__file__).parent


def main(model: str, out: str | None) -> int:
    if "DECKER_WIKTIONARY_HOST" in os.environ:
        pages.HOST = os.environ["DECKER_WIKTIONARY_HOST"]
    bench = json.loads((HERE / "checks.json").read_text(encoding="utf-8"))["languages"]

    results: dict[str, dict] = {}
    started = time.time()
    for key, block in bench.items():
        text = " ".join(block["sentences"])
        #: The run's own reporting is not the measurement, and it is long.
        with redirect_stderr(io.StringIO()):
            sentences = pipeline.run(text, target_lang=block["lang"], edition="en")
            built = G.build(
                sentences, target_lang=block["lang"], edition="en", model=model,
                host=os.environ.get("OLLAMA_HOST"), disambiguate=True, audio=False,
                concepts=False, rules=False,
            )
        #: Folded, because a card is fronted with Wiktionary's spelling: a
        #: sentence-initial `Хозяин` is glossed `хозяин`, and a check written
        #: from the text would never find it.
        kept: dict[str, list[str]] = {}
        for gloss in built:
            kept.setdefault(gloss.surface.casefold(), []).append(gloss.definition)

        outcomes = []
        for check in block["checks"]:
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
        "passed": counted.count("pass"),
        "failed": counted.count("fail"),
        "absent": counted.count("absent"),
        "glosses": sum(row["glosses"] for row in results.values()),
        "seconds": round(time.time() - started, 1),
        "languages": results,
    }
    print(f"{model}: {summary['passed']} passed, {summary['failed']} failed, "
          f"{summary['absent']} absent; {summary['glosses']} glosses, "
          f"{summary['seconds']:.0f}s")
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
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    sys.exit(main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None))

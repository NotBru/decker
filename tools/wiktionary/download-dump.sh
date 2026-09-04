#!/usr/bin/env bash
# Download one Wiktionary pages-articles dump, chunk by chunk, resumably.
#
#   EDITION=en DUMP_DATE=20260901 DUMP_DIR=~/dumps ./download-dump.sh
#
# The chunk list comes from the dump's own dumpstatus.json, so nothing has to be
# copied out of a directory listing by hand; it is written to $DUMP_DIR/chunks.txt
# and reused if it is already there. Each finished chunk appends a line to
# download.log, which is also what import-driver.sh reads to know a chunk is
# whole. Interrupted downloads resume rather than restart.
#
# See docs/execution/local-wiktionary.md for where this sits in the build.
set -euo pipefail

EDITION="${EDITION:-en}"
DUMP_DATE="${DUMP_DATE:?set DUMP_DATE to a dated dump, e.g. 20260901}"
DUMP_DIR="${DUMP_DIR:-$HOME/dumps}"
# Wikimedia asks that a client name itself and give a way to reach a human.
USER_AGENT="${DUMP_USER_AGENT:-decker-research/1.0 (https://github.com/NotBru/decker)}"

BASE="https://dumps.wikimedia.org/${EDITION}wiktionary/${DUMP_DATE}"
mkdir -p "$DUMP_DIR"
chunks="$DUMP_DIR/chunks.txt"
log="$DUMP_DIR/download.log"

if [ ! -s "$chunks" ]; then
  echo "listing chunks of ${EDITION}wiktionary-${DUMP_DATE}"
  curl -sSL -H "User-Agent: $USER_AGENT" "$BASE/dumpstatus.json" |
    python3 -c '
import json, sys
job = json.load(sys.stdin)["jobs"]["articlesdump"]
if job["status"] != "done":
    sys.exit("articlesdump is " + job["status"] + ", not done")
for name in sorted(job["files"]):
    print(name)
' > "$chunks"
fi

total=$(wc -l < "$chunks")
echo "$total chunks"

while read -r chunk; do
  [ -z "$chunk" ] && continue
  if grep -qx "done $chunk" "$log" 2>/dev/null; then continue; fi
  echo "fetching $chunk"
  # -C - resumes a partial file rather than starting it again.
  curl -sSL -C - -H "User-Agent: $USER_AGENT" -o "$DUMP_DIR/$chunk" "$BASE/$chunk"
  echo "done $chunk" >> "$log"
done < "$chunks"

echo "downloaded $(grep -c '^done ' "$log" 2>/dev/null || echo 0) / $total"

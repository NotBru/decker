#!/usr/bin/env bash
# Import downloaded dump chunks into a MediaWiki, one at a time.
#
#   MW_HOME=~/mw DUMP_DIR=~/dumps ./import-driver.sh
#
# Sequential on purpose: parallel importers race to create the same actor rows
# and the losers die with a null-user TypeError. One at a time still reaches
# ~1,500 pages/sec, because the database is the limit and not the number of
# processes. --no-updates skips the secondary link/search updates, which would
# mean parsing every page and running Lua for each; docs/execution/local-wiktionary.md
# says what that costs and why it is worth it.
#
# A chunk that has been imported is marked by an empty ok-<chunk> file, so a
# rerun after a crash resumes rather than repeating. A chunk that fails
# MAX_FAILURES times is given up on and named at the end: importDump.php throws
# on a content model this wiki has no handler for, and it will throw at the same
# place every time. strip-flow.py is the answer to that one -- see the runbook.
set -uo pipefail

MW_HOME="${MW_HOME:-$HOME/mw}"
DUMP_DIR="${DUMP_DIR:-$HOME/dumps}"
MAX_FAILURES="${MAX_FAILURES:-3}"
# How long to wait before looking again for chunks that are still downloading.
WAIT="${WAIT:-60}"

chunks="$DUMP_DIR/chunks.txt"
[ -s "$chunks" ] || { echo "no chunk list at $chunks; run download-dump.sh first" >&2; exit 1; }
[ -f "$MW_HOME/maintenance/importDump.php" ] || { echo "no MediaWiki at $MW_HOME" >&2; exit 1; }
cd "$MW_HOME" || exit 1

declare -A failures=()
given_up=()

while :; do
  pending=0
  while read -r chunk; do
    [ -z "$chunk" ] && continue
    [ -e "$DUMP_DIR/ok-$chunk" ] && continue
    if [ "${failures[$chunk]:-0}" -ge "$MAX_FAILURES" ]; then continue; fi
    # Only a chunk the downloader has finished with is whole enough to read.
    if ! grep -qx "done $chunk" "$DUMP_DIR/download.log" 2>/dev/null; then pending=1; continue; fi

    echo "$(date +%H:%M:%S) START $chunk"
    php maintenance/importDump.php --no-updates "$DUMP_DIR/$chunk" \
      > "$DUMP_DIR/import-$chunk.log" 2>&1
    status=$?
    # importDump.php can fail with a zero status, so the log is read too.
    if [ $status -eq 0 ] && ! grep -q "TypeError\|Fatal error" "$DUMP_DIR/import-$chunk.log"; then
      touch "$DUMP_DIR/ok-$chunk"
      echo "$(date +%H:%M:%S) OK $chunk"
    else
      failures[$chunk]=$(( ${failures[$chunk]:-0} + 1 ))
      echo "$(date +%H:%M:%S) FAILED $chunk (${failures[$chunk]}/$MAX_FAILURES), see $DUMP_DIR/import-$chunk.log"
      if [ "${failures[$chunk]}" -ge "$MAX_FAILURES" ]; then
        given_up+=("$chunk")
        echo "$(date +%H:%M:%S) GIVING UP on $chunk -- a chunk that fails here fails in the"
        echo "  same place every time. If the log ends in MWUnknownContentModelException, filter it:"
        echo "    python3 tools/wiktionary/strip-flow.py $DUMP_DIR/$chunk $DUMP_DIR/filtered.xml"
        echo "    php maintenance/importDump.php --no-updates $DUMP_DIR/filtered.xml"
        echo "    touch $DUMP_DIR/ok-$chunk"
      else
        pending=1
      fi
    fi
  done < "$chunks"
  [ "$pending" = 0 ] && break
  sleep "$WAIT"
done

if [ ${#given_up[@]} -gt 0 ]; then
  echo "$(date +%H:%M:%S) NOT IMPORTED: ${given_up[*]}"
  exit 1
fi
echo "$(date +%H:%M:%S) ALL CHUNKS IMPORTED"

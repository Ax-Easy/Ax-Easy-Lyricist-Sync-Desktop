#!/bin/bash
# CI helper: run a command with a time limit; on timeout dump every Python thread's stack
# (LYRICIST_SYNC_FAULTHANDLER + SIGUSR1), then kill it.   mac/watchdog.sh SECONDS NAME cmd args...
SECS="$1"; NAME="$2"; shift 2
export LYRICIST_SYNC_FAULTHANDLER="$PWD/stack-$NAME.txt"
"$@" &
pid=$!
for ((i = 0; i < SECS; i++)); do
  kill -0 $pid 2>/dev/null || { wait $pid; exit $?; }
  sleep 1
done
echo "::error title=$NAME::timed out after ${SECS}s; Python stacks:"
kill -USR1 $pid; sleep 3
cat "$LYRICIST_SYNC_FAULTHANDLER"
kill -9 $pid 2>/dev/null
exit 124

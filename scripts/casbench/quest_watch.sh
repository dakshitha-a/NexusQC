#!/usr/bin/env bash
# Event stream for a QUESTDB benchmark run, for a session-side monitor.
#
#   scripts/casbench/quest_watch.sh [run]
#
# Prints one line per event worth acting on and nothing otherwise:
# a finished row that is not a clean "ok", a worker that exited without a
# result, a row given up on, a stop, RUN_COMPLETE, a runner that has vanished
# without saying so, and a heartbeat older than ten minutes (a stall). Every
# 25th completed row it also prints a one-line progress summary, so a long
# quiet stretch still says it is alive. Exits when the run completes or the
# runner is gone. Silence therefore means "running, nothing wrong"; the
# checks cover every way it can stop, not only the successful one.
set -uo pipefail
cd "$(dirname "$0")/../.."
run=${1:-main}
dir=.cache/casbench_quest/run/$run
py=${QUEST_PYTHON:-python3}
n=0
tail -n 0 -F "$dir/runner.log" 2>/dev/null | while IFS= read -r line; do
  case "$line" in
    *" done "*" status=ok "*|*" done "*" status=unrepresentable "*|*" done "*" status=not_converged "*|*" done "*" status=too_large "*)
      # Results, not alarms: an unrepresentable space is the engine's answer
      # for that state and is counted in the progress line, as is a
      # non-converged state average. Only failures of the run itself page.
      n=$((n + 1))
      if (( n % 25 == 0 )); then echo "progress: $("$py" scripts/casbench/quest_run.py --run "$run" --status)"; fi ;;
    *" done "*|*"exited without"*|*"giving up"*|*"stop requested"*|*"wall cap"*|*RUN_COMPLETE*|*adopted*)
      echo "$line" ;;
  esac
done &
tp=$!
while true; do
  pid=$(cat "$dir/runner.pid" 2>/dev/null || true)
  if grep -q RUN_COMPLETE "$dir/runner.log" 2>/dev/null; then sleep 5; break; fi
  if [[ -z "$pid" ]] || ! kill -0 "$pid" 2>/dev/null; then
    echo "RUNNER GONE (pid ${pid:-none}) without RUN_COMPLETE: resume with scripts/casbench/quest_ctl.sh resume $run"
    break
  fi
  if [[ -f $dir/heartbeat.json ]]; then
    age=$(( $(date +%s) - $(stat -c %Y "$dir/heartbeat.json") ))
    if (( age > 600 )); then echo "STALL: heartbeat ${age}s old"; fi
  fi
  sleep 60
done
kill "$tp" 2>/dev/null
pkill -P "$tp" 2>/dev/null || true

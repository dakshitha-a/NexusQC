#!/usr/bin/env bash
# Control the detached QUESTDB benchmark runner (scripts/casbench/quest_run.py).
#
#   scripts/casbench/quest_ctl.sh start  [run] [extra quest_run.py args]
#   scripts/casbench/quest_ctl.sh resume [run]     # same as start; skips finished rows
#   scripts/casbench/quest_ctl.sh status [run]     # one-line JSON summary
#   scripts/casbench/quest_ctl.sh stop   [run]     # SIGTERM: workers stop, rows retried on resume
#   scripts/casbench/quest_ctl.sh tail   [run]     # follow the runner's log
#
# `run` defaults to "main". The runner is started with setsid + nohup, in its
# own session and process group, so it survives the shell, the terminal and
# the Claude Code session that started it. Its state lives under
# .cache/casbench_quest/run/<run>/, and resume picks up from there: finished
# rows are never rerun, live workers left by a dead runner are adopted.
# A host reboot kills it like everything else; `resume` is then the recovery.
set -euo pipefail
cd "$(dirname "$0")/../.."
cmd=${1:-status}; shift || true
run=${1:-main}; shift || true
dir=.cache/casbench_quest/run/$run
py=${QUEST_PYTHON:-python3}

case "$cmd" in
  start|resume)
    mkdir -p "$dir"
    if [[ -f $dir/runner.pid ]] && kill -0 "$(cat "$dir/runner.pid")" 2>/dev/null; then
      echo "runner for '$run' is already alive (pid $(cat "$dir/runner.pid"))"; exit 0
    fi
    setsid nohup "$py" scripts/casbench/quest_run.py --run "$run" "$@" \
      >>"$dir/nohup.out" 2>&1 </dev/null &
    sleep 3
    echo "started: pid $(cat "$dir/runner.pid" 2>/dev/null || echo '?'), log $dir/runner.log"
    ;;
  status)
    "$py" scripts/casbench/quest_run.py --run "$run" --status
    ;;
  stop)
    if [[ -f $dir/runner.pid ]]; then kill -TERM "$(cat "$dir/runner.pid")" && echo "stop sent"; else echo "not running"; fi
    ;;
  tail)
    tail -F "$dir/runner.log"
    ;;
  *)
    echo "usage: $0 {start|resume|status|stop|tail} [run] [args]" >&2; exit 2
    ;;
esac

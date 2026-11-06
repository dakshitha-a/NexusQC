#!/usr/bin/env bash
# Spin this checkout's NexusQC stack down to free its GPU, and back up again.
#
#     scripts/stack_power.sh status          # what is running, what the GPU holds
#     scripts/stack_power.sh down            # stop the stack, unload the model
#     scripts/stack_power.sh down --force    # ...even if jobs are running
#     scripts/stack_power.sh up              # start the stack again
#
# WHY STOPPING THE CONTAINERS IS NOT ENOUGH
# -----------------------------------------
# The GPU is held by Ollama, not by any container in this stack. The api's
# model warmer (app/agent/model_warmer.py) loads the chat model with
# `keep_alive: -1`, which means "keep it until told otherwise", so the model
# stays resident after the api is gone. `down` therefore does two things, in
# this order: stop the containers, which ends the warmer, then tell Ollama to
# unload the models with `keep_alive: 0`. The other order would not work: the
# warmer re-loads the model every 60 seconds and would put it straight back.
# Nothing here touches the Ollama service itself, which may be shared.
#
# WHY `stop`/`start` AND NOT `down`/`up`
# --------------------------------------
# `docker compose stop` keeps the containers, networks and volumes exactly as
# they are; `start` is its exact inverse and cannot recreate or reconfigure
# anything. `up -d` could recreate a container whose config changed since it
# was built, which would advance the deployment outside scripts/update.sh.
# The restart policy is `unless-stopped`, so a stopped stack stays stopped
# across a reboot until `up` is run.
#
# Running jobs live inside the api container and die with it, with no resume,
# so `down` refuses while any job is running unless given --force. Queued jobs
# are safe: they are re-queued when the api starts again.
#
# Ollama's address: QC_AGENT_OLLAMA_HOST in .env usually names
# host.docker.internal, which only resolves inside a container, so this
# script talks to http://localhost:11434 unless STACK_POWER_OLLAMA_URL says
# otherwise.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
QC_PREFIX="stack_power"
# shellcheck source=lib/common.sh
. scripts/lib/common.sh

[ -f .env ] || die "no .env in ${ROOT} -- is this a deployment checkout?"

QC_COMPOSE=(docker compose -f docker-compose.yml)
[ -f docker-compose.override.yml ] && QC_COMPOSE+=(-f docker-compose.override.yml)

OLLAMA_URL="${STACK_POWER_OLLAMA_URL:-http://localhost:11434}"
LLM_MODEL="$(envget .env QC_AGENT_LLM_MODEL)"; LLM_MODEL="${LLM_MODEL:-qwen3.8:27b}"
EMBED_MODEL="$(envget .env QC_AGENT_EMBEDDING_MODEL)"; EMBED_MODEL="${EMBED_MODEL:-nomic-embed-text}"

running_services() {
    "${QC_COMPOSE[@]}" ps --status running --services 2>/dev/null || true
}

# One line per job whose status.json says "running". Same test as
# scripts/check_destructive.sh uses before an update.
running_jobs() {
    [ -d data/jobs ] || return 0
    python3 - data/jobs <<'PY'
import json, os, sys
root = sys.argv[1]
for name in sorted(os.listdir(root)):
    p = os.path.join(root, name, "status.json")
    try:
        with open(p) as fh:
            d = json.load(fh)
    except Exception:
        continue
    if d.get("status") == "running":
        print("%s  %s" % (name, (d.get("message") or "")[:60]))
PY
}

# Models Ollama currently has loaded, one name per line.
loaded_models() {
    curl -fsS --max-time 10 "${OLLAMA_URL}/api/ps" 2>/dev/null | python3 -c '
import json, sys
try:
    for m in json.load(sys.stdin).get("models", []):
        print(m["name"])
except Exception:
    pass'
}

unload_model() {
    # No "prompt" key: a load/unload request that generates nothing.
    curl -fsS --max-time 60 "${OLLAMA_URL}/api/generate" \
        -d "{\"model\": \"$1\", \"keep_alive\": 0}" >/dev/null
}

show_gpus() {
    command -v nvidia-smi >/dev/null 2>&1 || { info "nvidia-smi not found"; return 0; }
    echo "  GPU memory in use:"
    nvidia-smi --query-gpu=index,memory.used,memory.total --format=csv,noheader \
        | sed 's/^/    GPU /'
    local apps
    apps="$(nvidia-smi --query-compute-apps=pid,process_name,used_memory --format=csv,noheader 2>/dev/null \
        | grep -i ollama || true)"
    if [ -n "$apps" ]; then
        echo "  Ollama processes on a GPU:"
        printf '%s\n' "$apps" | sed 's/^/    /'
    else
        echo "  No Ollama process holds a GPU."
    fi
}

cmd_status() {
    local svcs models
    svcs="$(running_services)"
    if [ -n "$svcs" ]; then
        ok "stack is UP: $(printf '%s' "$svcs" | tr '\n' ' ')"
    else
        ok "stack is DOWN"
    fi
    models="$(loaded_models)"
    if [ -n "$models" ]; then
        ok "Ollama has loaded: $(printf '%s' "$models" | tr '\n' ' ')"
    else
        ok "Ollama has no model loaded"
    fi
    show_gpus
}

cmd_down() {
    local force="$1" jobs svcs m left
    jobs="$(running_jobs)"
    if [ -n "$jobs" ]; then
        if [ "$force" != 1 ]; then
            die "these jobs are running and would be killed:
$(printf '%s\n' "$jobs" | sed 's/^/    /')
  Wait for them to finish, or run again with --force to kill them."
        fi
        warn "killing running jobs, as --force asked:"
        printf '%s\n' "$jobs" | sed 's/^/    /'
    fi

    svcs="$(running_services)"
    if [ -n "$svcs" ]; then
        info "stopping the stack (containers and data are kept)"
        "${QC_COMPOSE[@]}" stop
        ok "stack stopped"
    else
        ok "stack was already stopped"
    fi

    for m in "$LLM_MODEL" "$EMBED_MODEL"; do
        if loaded_models | grep -qxF -e "$m" -e "${m}:latest"; then
            unload_model "$m" && ok "unloaded ${m} from Ollama" || warn "could not unload ${m}"
        fi
    done

    # Ollama unloads asynchronously; give the runner a moment to exit.
    for _ in 1 2 3 4 5 6 7 8 9 10; do
        left="$(loaded_models)"
        [ -z "$left" ] && break
        sleep 1
    done
    if [ -n "$left" ]; then
        warn "Ollama still has loaded: $(printf '%s' "$left" | tr '\n' ' ')"
        warn "These are not this stack's models, so they were left alone."
    fi
    show_gpus
    echo
    echo "  The site is unreachable until you run: scripts/stack_power.sh up"
}

cmd_up() {
    local svcs
    "${QC_COMPOSE[@]}" ps -a --services 2>/dev/null | grep -q . \
        || die "this stack has no containers to start. Use scripts/install.sh or scripts/update.sh."
    info "starting the stack"
    "${QC_COMPOSE[@]}" start
    info "waiting for the app to answer its health check"
    local rc=0
    qc_wait_for_health 300 "$(health_urls)" || rc=$?
    case "$rc" in
        0) ok "healthy at ${QC_HEALTH_URL}" ;;
        2) die "a container exited while starting: ${QC_STOPPED_SERVICES:-}. See: docker compose logs" ;;
        *) die "no healthy answer after 300 s. See: docker compose logs api" ;;
    esac
    info "the api's model warmer reloads ${LLM_MODEL} within about a minute"
    svcs="$(running_services)"
    ok "running: $(printf '%s' "$svcs" | tr '\n' ' ')"
}

case "${1:-status}" in
    status) cmd_status ;;
    down)
        FORCE=0
        [ "${2:-}" = "--force" ] && FORCE=1
        cmd_down "$FORCE"
        ;;
    up) cmd_up ;;
    -h|--help|help) sed -n '2,7p' "$0" | sed 's/^# \{0,1\}//' ;;
    *) die "unknown command '$1'. Use: status, down [--force], or up." ;;
esac

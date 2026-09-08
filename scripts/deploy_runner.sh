#!/usr/bin/env bash
# The host side of the admin panel's Deployment section.
#
# WHY THIS EXISTS AT ALL
# ----------------------
# The api process cannot update its own deployment, and giving it the means to
# would be the wrong trade. It runs in a container whose only bind mount is
# ./data; it has no .git, no checkout, no npm, no psql, and no docker socket.
# And `docker compose up -d` destroys the very container serving the admin's
# request, so even with the tools it could not see the update through.
#
# The obvious shortcut is to bind-mount /var/run/docker.sock into the api
# container. That is rejected deliberately: the docker socket is
# root-equivalent on the host, so it would turn any remote-code-execution bug
# in a multi-user web application into host root. The same objection applies to
# having the api spawn a sibling updater container.
#
# So the api writes a request into the one directory both sides can see, and
# this script -- running on the host, as the operator, triggered by a systemd
# .path unit -- picks it up. It never executes anything the request contains.
# The action must be one of a fixed set, and a ref is resolved and checked to
# be on origin/main before it is passed on as a plain sha.
#
# WHAT THE BROWSER READS
# ----------------------
# Progress is written into data/deploy/<id>/, which nginx also serves read-only
# at /deploy-status/. That matters: while `compose up -d` recreates the api,
# there is no api to ask, and a progress bar that stops moving for ninety
# seconds is indistinguishable from one that has died. nginx is not recreated
# by an api-only rebuild, so it keeps answering throughout.
#
# Usage:
#     scripts/deploy_runner.sh              # process one pending request
#     scripts/deploy_runner.sh --watch      # poll, for hosts without systemd
#
# Exit status is about the runner, not about the update: a request that fails
# is recorded as failed in its own status.json and is not an error here.
set -euo pipefail

# Everything runs inside main() so bash parses the whole file before executing
# any of it. This script invokes update.sh, which fast-forwards the checkout
# that contains BOTH scripts -- so without this, git can rewrite the file while
# bash is still reading it and bash resumes at its old byte offset in the new
# one. See the same comment in scripts/update.sh.
main() {

SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SELF_DIR/.." && pwd)"
cd "$REPO_ROOT"

DEPLOY_DIR="data/deploy"
REQUEST="$DEPLOY_DIR/request.json"
RUNNER_STATE="$DEPLOY_DIR/runner.json"

log() { printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*"; }

# The api asks "is anything actually there?" by writing a ping and waiting for
# this file to be refreshed. Installed-but-dead and installed-and-working look
# identical from inside the container otherwise, and an Apply button that
# silently does nothing is worse than no button.
touch_runner_state() {
    mkdir -p "$DEPLOY_DIR"
    printf '{"alive_at": %s, "pid": %s, "repo": "%s"}\n' \
        "$(date -u +%s)" "$$" "$REPO_ROOT" > "$RUNNER_STATE.tmp"
    mv -f "$RUNNER_STATE.tmp" "$RUNNER_STATE"
}

# status.json is rewritten in full at every step rather than appended to, so a
# reader always gets a complete document. Written to a temp file and renamed,
# because the browser polls this through nginx and half a JSON document parses
# as an error rather than as "not ready yet".
write_status() {
    local dir="$1" state="$2" step="$3" extra="${4:-}"
    python3 - "$dir/status.json" "$state" "$step" "$extra" <<'PY'
import json, os, sys, time
path, state, step, extra = sys.argv[1:5]
doc = {}
if os.path.exists(path):
    try:
        doc = json.load(open(path))
    except Exception:
        doc = {}
doc.update({"state": state, "step": step, "updated_at": time.time()})
if extra:
    try:
        doc.update(json.loads(extra))
    except Exception:
        doc["note"] = extra
tmp = path + ".tmp"
with open(tmp, "w") as fh:
    json.dump(doc, fh, indent=2)
os.replace(tmp, path)
PY
}

process_one() {
    [ -f "$REQUEST" ] || return 0

    # Claim the request by moving it before doing anything else. A systemd
    # .path unit fires on the file EXISTING, so leaving it in place means the
    # unit never triggers again -- and worse, a slow run and a new request can
    # otherwise be handled twice.
    local id
    id="$(python3 -c "
import json,sys
try:
    print((json.load(open('$REQUEST')).get('id') or '').strip())
except Exception:
    print('')
" 2>/dev/null || true)"

    # An id becomes a path segment and is served over http, so it is validated
    # rather than trusted. Anything unexpected gets a generated one and the
    # request is still recorded, so a malformed request is visible rather than
    # silently dropped.
    case "$id" in
        ""|*[!A-Za-z0-9_-]*) id="malformed-$(date -u +%s)" ;;
    esac

    local dir="$DEPLOY_DIR/$id"
    mkdir -p "$dir"
    mv -f "$REQUEST" "$dir/request.json"

    local action ref drain force
    action="$(python3 -c "import json;print(json.load(open('$dir/request.json')).get('action',''))" 2>/dev/null || true)"
    ref="$(python3 -c "import json;print(json.load(open('$dir/request.json')).get('ref') or '')" 2>/dev/null || true)"
    drain="$(python3 -c "import json;print('1' if json.load(open('$dir/request.json')).get('drain') else '0')" 2>/dev/null || echo 0)"
    force="$(python3 -c "import json;print('1' if json.load(open('$dir/request.json')).get('force') else '0')" 2>/dev/null || echo 0)"

    write_status "$dir" running "starting"
    : > "$dir/log.txt"

    # A fixed set. Nothing from the request is ever handed to a shell.
    case "$action" in
        ping)
            write_status "$dir" done "the runner is alive"
            return 0 ;;
        report|update|rollback) ;;
        *)
            write_status "$dir" failed "unknown action" \
                "{\"error\": \"unknown action: $(printf '%s' "$action" | tr -cd 'A-Za-z0-9_-')\"}"
            return 0 ;;
    esac

    # Resolve the ref here and pass a sha onward. An operator's ref is a
    # convenience; what actually gets deployed should never depend on what
    # origin/main happened to point at by the time update.sh looked.
    git fetch --quiet origin 2>>"$dir/log.txt" || true
    local target_sha=""
    if [ -n "$ref" ]; then
        target_sha="$(git rev-parse --verify --quiet "${ref}^{commit}" 2>/dev/null || true)"
    else
        target_sha="$(git rev-parse --verify --quiet "origin/main^{commit}" 2>/dev/null || true)"
    fi
    if [ "$action" != "rollback" ] && [ -z "$target_sha" ]; then
        write_status "$dir" failed "cannot resolve target" "{\"error\": \"cannot resolve ref\"}"
        return 0
    fi

    # An arbitrary sha is not deployable just because it exists in the object
    # database. It has to be something origin/main can reach or be reached
    # from, which is what makes this an update rather than a way to run
    # anything anyone can push to any branch.
    if [ "$action" = "update" ]; then
        if ! git merge-base --is-ancestor "$target_sha" origin/main 2>/dev/null \
           && ! git merge-base --is-ancestor origin/main "$target_sha" 2>/dev/null; then
            write_status "$dir" failed "target is not on origin/main" \
                "{\"error\": \"refusing a commit that is neither an ancestor nor a descendant of origin/main\"}"
            return 0
        fi
    fi

    local rc=0
    case "$action" in
        report)
            write_status "$dir" running "checking what this would do"
            if bash scripts/check_destructive.sh --to "$target_sha" --json \
                    > "$dir/report.json" 2>>"$dir/log.txt"; then rc=0; else rc=$?; fi
            # 1 means "found something destructive", which is a result, not a
            # failure of the check. Only 2 means it could not run.
            # What the update would actually bring in. An impact report says
            # what would BREAK; this says what would CHANGE, which is the
            # other half of the question an admin is answering and is
            # otherwise only available by reading the repository on the host.
            git log --oneline --no-decorate "HEAD..${target_sha}" 2>/dev/null \
                | head -50 > "$dir/changes.txt" || true
            if [ "$rc" -ge 2 ]; then
                write_status "$dir" failed "the impact report could not be produced" "{\"error\": \"check_destructive exited $rc\"}"
            else
                write_status "$dir" done "report ready" "{\"destructive\": $rc, \"target\": \"$target_sha\"}"
            fi
            ;;
        update)
            local args=(--yes --maintenance)
            [ "$drain" -eq 1 ] && args+=(--drain)
            [ "$force" -eq 1 ] && args+=(--force)
            write_status "$dir" running "updating" "{\"target\": \"$target_sha\"}"
            # stdbuf so the log is readable while it runs rather than only
            # after: a progress view fed by a buffered pipe cannot be told
            # apart from a hung one, which is what makes people wait.
            if stdbuf -oL -eL bash scripts/update.sh "${args[@]}" "$target_sha" \
                    >>"$dir/log.txt" 2>&1; then
                write_status "$dir" done "updated" "{\"target\": \"$target_sha\"}"
            else
                rc=$?
                write_status "$dir" failed "the update did not complete" "{\"exit_code\": $rc}"
            fi
            ;;
        rollback)
            write_status "$dir" running "rolling back"
            if stdbuf -oL -eL bash scripts/update.sh --yes --maintenance --rollback \
                    >>"$dir/log.txt" 2>&1; then
                write_status "$dir" done "rolled back"
            else
                rc=$?
                write_status "$dir" failed "the rollback did not complete" "{\"exit_code\": $rc}"
            fi
            ;;
    esac

    # Mirrored so the api can show update history: .update-log lives at the
    # repo root, which the container cannot see, and only ./data is shared.
    [ -f .update-log ] && cp -f .update-log "$DEPLOY_DIR/update-log.txt" || true
    return 0
}

touch_runner_state
if [ "${1:-}" = "--watch" ]; then
    log "watching $DEPLOY_DIR for requests"
    while :; do
        touch_runner_state
        process_one || log "a request failed to process; continuing"
        sleep 3
    done
else
    process_one
fi

}

main "$@"

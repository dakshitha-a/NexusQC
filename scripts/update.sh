#!/usr/bin/env bash
# Updates a NexusQC deployment (one produced by scripts/install.sh) to a
# newer commit from the git remote it was cloned from.
#
# WHICH REMOTE THIS PULLS FROM
# -----------------------------
# This script always fetches and resolves refs against this checkout's own
# `origin` -- whatever that is. For a deployment created by scripts/install.sh,
# that is the git URL `git clone` was pointed at during install -- for most
# installs, the public NexusQC release repository.
#
# WHAT "CURRENTLY RUNNING" MEANS HERE
# -----------------------------------
# This script asks the DEPLOYMENT what it is running, not the checkout. The
# api image carries the commit it was built from as an OCI revision label
# (Dockerfile), and the built frontend bundle carries the same in
# frontend/dist/.build-commit. Those are the two halves of what is actually
# serving traffic, and on a deployment produced by scripts/install.sh -- one
# directory that is both the git working copy and the running stack -- either
# can sit behind HEAD for as long as nobody rebuilds. An earlier version of
# this script compared `git rev-parse HEAD` against the target and so reported
# "already up to date -- nothing to do" whenever the checkout had been
# committed but not rebuilt, sending the operator to a hand-run
# `docker compose up --build` that skips every gate below. See
# docs/trackers/2026-08-update-knows-what-it-runs.md.
#
# A stamp that is missing or `unknown` means the image was built outside this
# script. That is read as "cannot tell, so assume stale" and the update runs;
# it is never read as up to date.
#
# WHAT IT DOES, IN ORDER
#   1. refuses if the tree is dirty
#   2. fetches origin
#   3. reports what the change will do to the running deployment, via
#      scripts/check_destructive.sh, and refuses to continue past anything
#      destructive without an explicit decision
#   4. takes a FULL backup (database + all of data/), unconditionally --
#      there is no separate stack to fall back to if something goes wrong
#   5. optionally drains jobs, by stopping admission and waiting
#   6. fast-forwards to the target commit, rebuilds the frontend and image,
#      brings the stack up
#   7. waits for health, restores job admission, records what it did AND
#      whether it came up healthy -- an unhealthy deployment is never
#      recorded as a good commit to roll back to
#
# Usage:
#     scripts/update.sh                    # update to origin/main
#     scripts/update.sh <ref>              # update to a specific commit or tag
#     scripts/update.sh --dry-run          # run every gate, change nothing
#     scripts/update.sh --drain            # wait for running jobs to finish
#     scripts/update.sh --force            # accept killing in-flight jobs
#     scripts/update.sh --yes              # accept the destructive report
#     scripts/update.sh --maintenance      # lock users out for the restart
#     scripts/update.sh --rollback         # go back to the last healthy commit
set -euo pipefail

# Sourced HERE, above main(), and that placement is load-bearing for the same
# reason main() itself is. This script fast-forwards the checkout it is running
# from; a `source` executed after that point would read a different library
# than the one this script was written against. Executed here it is read, and
# its functions are in memory, before git touches anything.
_SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/lib/common.sh
source "${_SELF_DIR}/lib/common.sh"
QC_PREFIX="update"

# Everything below runs inside a function so that bash parses the whole file
# before executing any of it.
#
# This is not style. Below, this script fast-forwards the checkout it is
# running from -- and scripts/update.sh is a tracked file in that checkout. If
# the update changes this script, git rewrites it on disk while bash is
# part-way through reading it, and bash carries on at its old byte offset in
# the new file: it resumes mid-token, in the middle of a different line, and
# does whatever that happens to spell. The failure is silent, unrepeatable and
# arrives at the worst possible moment, halfway through recreating a live
# deployment. Reading to the closing brace first makes it impossible.
#
# Do not unwrap this.
main() {
    # Colours, die/ok/info/warn/step, envget, the preflight checks and the
    # health wait all come from scripts/lib/common.sh, sourced above.
    SELF_DIR="$_SELF_DIR"
    REPO_ROOT="$(cd "$SELF_DIR/.." && pwd)"
    cd "$REPO_ROOT"

    UPDATE_LOG=".update-log"

    TARGET_REF=""
    DRY_RUN=0; ASSUME_YES=0; DRAIN=0; FORCE=0; ROLLBACK=0; MAINTENANCE=0
    DRAIN_TIMEOUT="${QC_AGENT_DRAIN_TIMEOUT:-14400}"   # 4h: a CASSCF run is not an outlier here

    while [ $# -gt 0 ]; do
        case "$1" in
            --dry-run)  DRY_RUN=1; shift ;;
            --yes|-y)   ASSUME_YES=1; shift ;;
            --maintenance) MAINTENANCE=1; shift ;;
            --drain)    DRAIN=1; shift ;;
            --force)    FORCE=1; shift ;;
            --rollback) ROLLBACK=1; shift ;;
            -h|--help)  sed -n '2,53p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
            -*)         die "unknown option: $1" ;;
            *)          [ -z "$TARGET_REF" ] || die "more than one ref given"; TARGET_REF="$1"; shift ;;
        esac
    done

    [ "$DRAIN" -eq 1 ] && [ "$FORCE" -eq 1 ] && die "--drain and --force contradict each other."

    step "checking this host"
    require_tools git docker openssl curl
    require_docker
    ok "git, docker, docker compose, openssl and curl are all present and working"

    step "checking this checkout is clean"

    [ -z "$(git status --porcelain)" ] || die "this checkout has local modifications:
    $(git status --short | sed 's/^/    /')
      An update needs a clean, identifiable commit -- otherwise a rollback has
      nothing to return to. Commit or discard these first."
    ok "clean tree"

    [ -f .env ] || die "no .env -- run scripts/install.sh first, or see docs/DEPLOYMENT.md."

    COMPOSE=(docker compose -f docker-compose.yml)
    if [ -f docker-compose.override.yml ]; then
        COMPOSE+=(-f docker-compose.override.yml)
    else
        warn "no docker-compose.override.yml: ORCA and BAGEL will NOT be mounted."
        warn "If this deployment is supposed to run them, stop and restore it first."
    fi

    PGUSER_VAL="$(envget .env QC_AGENT_POSTGRES_USER)"; PGUSER_VAL="${PGUSER_VAL:-qc_agent}"
    PGDB_VAL="$(envget .env QC_AGENT_POSTGRES_DB)";     PGDB_VAL="${PGDB_VAL:-qc_agent}"
    # health_urls() -- where to knock to see whether the deployment came up --
    # now lives in scripts/lib/common.sh, because install.sh needs it too and
    # had been hardcoding 127.0.0.1:8443 instead. It reads QC_COMPOSE.
    QC_COMPOSE=("${COMPOSE[@]}")

    DIST_STAMP="frontend/dist/.build-commit"

    # What the api image was built from, read back off the OCI revision label the
    # Dockerfile stamps. Prefers the RUNNING container over the built image: those
    # differ whenever an image was built but never brought up, and the question
    # being asked is what is serving traffic right now, not what is on disk.
    #
    # Returns nothing at all when the answer is not knowable -- no stamp, the
    # literal `unknown` a hand-run build leaves, or a commit this checkout has
    # never heard of. Every caller below treats "not knowable" as stale rather
    # than as current, so an unstamped deployment gets updated instead of being
    # waved through.
    deployed_commit() {
        local cid="" img="" rev=""
        # Every step below tolerates failure rather than propagating it. A stopped
        # or half-built deployment is a normal thing to be running an update
        # against, and "cannot tell" is a perfectly good answer here -- callers
        # read it as stale. Aborting instead would refuse to update the
        # deployments most in need of one.
        cid="$("${COMPOSE[@]}" ps -q api 2>/dev/null | head -n1 || true)"
        if [ -n "$cid" ]; then
            rev="$(docker inspect --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' "$cid" 2>/dev/null || true)"
        fi
        if [ -z "$rev" ] || [ "$rev" = "<no value>" ]; then
            img="$("${COMPOSE[@]}" images -q api 2>/dev/null | head -n1 || true)"
            if [ -n "$img" ]; then
                rev="$(docker inspect --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' "$img" 2>/dev/null || true)"
            fi
        fi
        case "$rev" in ""|unknown|"<no value>") return 0 ;; esac
        git rev-parse --verify --quiet "${rev}^{commit}" 2>/dev/null || true
    }

    # The other half of the deployment. nginx serves frontend/dist from a host
    # bind mount, so the bundle is not in the image and a current image says
    # nothing about it -- this is the same trap the image label closes, one layer
    # out. Written by the rebuild step below; absent on a deployment that has not
    # been through this script since the stamp existed.
    deployed_frontend_commit() {
        local rev=""
        [ -f "$DIST_STAMP" ] || return 0
        rev="$(tr -d '[:space:]' < "$DIST_STAMP" 2>/dev/null || true)"
        [ -n "$rev" ] || return 0
        git rev-parse --verify --quiet "${rev}^{commit}" 2>/dev/null || true
    }

    CHECKOUT_SHA="$(git rev-parse HEAD)"
    DEPLOYED_SHA="$(deployed_commit)"
    DEPLOYED_UI_SHA="$(deployed_frontend_commit)"

    step "resolving what to update to"

    if [ "$ROLLBACK" -eq 1 ]; then
        [ -z "$TARGET_REF" ] || die "--rollback takes no ref."
        [ -f "$UPDATE_LOG" ] || die "no ${UPDATE_LOG} -- nothing to roll back to.
      This file is written by this script on every successful update; without it
      there is no record of what was deployed before."
        # The most recent commit this deployment is known to have run HEALTHILY,
        # which is not the same as the previous line's commit. An update whose
        # health check failed is recorded with the `unhealthy` verb (see
        # record_update below), and rolling back onto one of those would return
        # the deployment to a commit that never came up -- the failure mode the
        # old `tail -n1` of `$1=="updated"` had, once a bad update was followed by
        # another one. Tracks the running commit and the last healthy one side by
        # side: if the deployment is sitting ON the last healthy commit there is
        # nothing to undo but the one before it, and otherwise the last healthy
        # commit IS the thing to return to. Logs written before the verb existed
        # contain only `updated` lines and resolve exactly as they did before.
        PREV="$(awk '
            NR==1 { good=$4; prev_good=$4 }
            { cur=$3; if ($1=="updated") { prev_good=good; good=$3 } }
            END { if (good != cur) print good; else print prev_good }
        ' "$UPDATE_LOG")"
        [ -n "$PREV" ] || die "${UPDATE_LOG} has no previous commit recorded."
        TARGET_SHA="$(git rev-parse --verify --quiet "${PREV}^{commit}" || true)"
        [ -n "$TARGET_SHA" ] || die "the previous commit ${PREV} is not in this checkout's object store."
        warn "rolling back to ${TARGET_SHA:0:12} -- code only."
        warn "Database columns added by the update you are undoing STAY. The schema"
        warn "is forward-only and idempotent; the pre-update backup is the only way"
        warn "to undo it, and restoring it also rewinds every account, session and"
        warn "conversation created since. Almost never what you want -- see"
        warn "scripts/restore.sh if you really mean to go that far."
    else
        info "fetching origin"
        git fetch --quiet --tags origin || die "git fetch failed."
        TARGET_REF="${TARGET_REF:-origin/main}"
        TARGET_SHA="$(git rev-parse --verify --quiet "${TARGET_REF}^{commit}" || true)"
        [ -n "$TARGET_SHA" ] || die "cannot resolve ref: ${TARGET_REF}"
    fi

    subject() { git log -1 --format=%s "$1" 2>/dev/null || echo '(unknown commit)'; }

    echo "  checkout is at:     ${CHECKOUT_SHA:0:12}  $(subject "$CHECKOUT_SHA")"
    if [ -n "$DEPLOYED_SHA" ]; then
        echo "  api image built from: ${DEPLOYED_SHA:0:12}  $(subject "$DEPLOYED_SHA")"
    else
        echo "  api image built from: ${YEL}unknown${RST} (no build stamp -- built outside this script)"
    fi
    if [ -n "$DEPLOYED_UI_SHA" ]; then
        echo "  frontend built from:  ${DEPLOYED_UI_SHA:0:12}  $(subject "$DEPLOYED_UI_SHA")"
    else
        echo "  frontend built from:  ${YEL}unknown${RST} (no ${DIST_STAMP})"
    fi
    echo "  updating to:        ${TARGET_SHA:0:12}  $(subject "$TARGET_SHA")"

    # Up to date means all three agree with the target, and "unknown" is never
    # taken as agreement -- an unstamped deployment is rebuilt once, which stamps
    # it, and reports honestly from then on. The frontend is exempt only when
    # the bundle comes out of the api image now, so any host that can build the
    # image can also install the bundle. There is no longer a "this host
    # physically cannot rebuild the frontend" case to make an exception for.
    UI_CURRENT=0
    if [ -n "$DEPLOYED_UI_SHA" ] && [ "$DEPLOYED_UI_SHA" = "$TARGET_SHA" ]; then
        UI_CURRENT=1
    fi

    if [ "$CHECKOUT_SHA" = "$TARGET_SHA" ] \
       && [ -n "$DEPLOYED_SHA" ] && [ "$DEPLOYED_SHA" = "$TARGET_SHA" ] \
       && [ "$UI_CURRENT" -eq 1 ]; then
        ok "already up to date -- nothing to do."
        exit 0
    fi

    # The checkout is already where it needs to be and only the build is behind.
    # This is the case the old HEAD comparison called "nothing to do": it must
    # still take the backup, the destructive report and the drain, but it has no
    # git move to make -- and it must not write an ${UPDATE_LOG} entry, because
    # such an entry would name the same commit as both the new and the previous
    # one and --rollback would resolve it to a no-op.
    REBUILD_ONLY=0
    if [ "$CHECKOUT_SHA" = "$TARGET_SHA" ]; then
        REBUILD_ONLY=1
        info "the checkout is already at the target; only the build is behind"
    fi

    # What the change is measured AGAINST: what is deployed, when that is known
    # and is on the way to the target. Falls back to the checkout otherwise --
    # including the case where the running image is somehow NOT an ancestor of the
    # target, where a diff would be reversed and the destructive report would read
    # backwards.
    REPORT_FROM="$CHECKOUT_SHA"
    if [ -n "$DEPLOYED_SHA" ] && git merge-base --is-ancestor "$DEPLOYED_SHA" "$TARGET_SHA" 2>/dev/null; then
        REPORT_FROM="$DEPLOYED_SHA"
    elif [ -n "$DEPLOYED_SHA" ] && [ "$ROLLBACK" -eq 0 ]; then
        warn "the running image (${DEPLOYED_SHA:0:12}) is not an ancestor of the target;"
        warn "reporting the change against the checkout instead."
    fi

    if [ "$ROLLBACK" -eq 0 ]; then
        git merge-base --is-ancestor "$CHECKOUT_SHA" "$TARGET_SHA" \
            || die "the checkout's commit is not an ancestor of ${TARGET_REF} -- this is not a
      straightforward fast-forward (local history has diverged from the release
      stream). Resolve that by hand before re-running -- an update script should
      not guess how to reconcile diverged history."
    fi

    # --- the destructive-change report ----------------------------------------
    step "what this will do to the running deployment"

    # Said out loud rather than left to be inferred from a report that reads
    # reassuringly empty. With no build stamp there is no commit to diff the
    # running image against, so the report below can only describe the checkout's
    # own movement -- which for a rebuild-only update is no movement at all. It is
    # not evidence that the running containers already have these changes.
    if [ -z "$DEPLOYED_SHA" ]; then
        warn "the running image carries no build stamp, so this report is measured"
        warn "from the checkout (${REPORT_FROM:0:12}) and CANNOT show what the"
        warn "containers are missing. After this update it will be stamped, and"
        warn "every later report will be measured from what is genuinely deployed."
    fi

    set +e
    bash scripts/check_destructive.sh --from "$REPORT_FROM" --to "$TARGET_SHA" --stack-dir "$REPO_ROOT"
    IMPACT_RC=$?
    set -e

    if [ "$IMPACT_RC" -eq 2 ]; then
        die "the impact report could not run. Not updating blind."
    fi

    # Remembered rather than only acted on: what to advise if this goes wrong
    # later depends on it. --rollback moves code and nothing else, so after a
    # destructive change it would leave the old code against the migrated
    # database -- the backup is the only thing that undoes one.
    DESTRUCTIVE=0
    [ "$IMPACT_RC" -eq 1 ] && DESTRUCTIVE=1

    if [ "$IMPACT_RC" -eq 1 ]; then
        if [ "$DRY_RUN" -eq 1 ]; then
            warn "destructive changes found (see above). This is a dry run; stopping here."
            exit 1
        fi
        if [ "$ASSUME_YES" -eq 0 ]; then
            echo "${RED}The report above found changes that lose work or fail silently.${RST}"
            echo "Read it, then decide. Nothing has been changed yet."
            echo
            printf 'Type UPDATE to go ahead anyway: '
            read -r reply
            [ "$reply" = "UPDATE" ] || die "aborted -- nothing was touched."
        else
            warn "destructive changes accepted via --yes"
        fi
    fi

    # An allow-list: does anything in this change affect what is actually
    # RUNNING, or is it documentation the operator can pull in without
    # disturbing in-flight jobs?
    RUNTIME_IRRELEVANT_RE='^(docs/|CHANGELOG\.md$|README\.md$|NOTICE\.md$|CLAUDE\.md$|LICENSE$|CITATION\.cff$|\.gitignore$)'
    CHANGED_FILES="$(git diff --name-only "$REPORT_FROM" "$TARGET_SHA")"
    NEEDS_RESTART=1
    if [ -n "$CHANGED_FILES" ] && ! printf '%s\n' "$CHANGED_FILES" | grep -qvE "$RUNTIME_IRRELEVANT_RE"; then
        NEEDS_RESTART=0
        ok "documentation-only change: the running containers will be left alone"
    fi

    # Running and pending are counted SEPARATELY, because the restart does
    # two different things to them and this used to say it did one (R-056).
    # A running job has a live worker that a restart kills, and there is no
    # resume. A pending job was never admitted, has no worker_pid in its
    # meta.json, and case 3 of JobManager._reconcile_orphaned_jobs re-enqueues
    # it "exactly as if freshly submitted" on the next start. Reporting both
    # as "will be killed" pushed an operator whose only jobs were queued into
    # a four-hour drain or an unnecessary --force.
    count_by_state() {
        [ -d data/jobs ] || { echo "0 0"; return; }
        python3 - data/jobs <<'PY'
import json, os, sys
root = sys.argv[1]
running = pending = 0
for name in os.listdir(root):
    p = os.path.join(root, name, "status.json")
    if not os.path.isfile(p):
        continue
    try:
        with open(p) as fh:
            st = json.load(fh).get("status")
    except Exception:
        continue
    if st == "running":
        running += 1
    elif st == "pending":
        pending += 1
print(running, pending)
PY
    }

    read -r RUNNING_JOBS PENDING_JOBS <<EOF
$(count_by_state)
EOF
    INFLIGHT=$((RUNNING_JOBS + PENDING_JOBS))
    if [ "$PENDING_JOBS" -gt 0 ]; then
        ok "${PENDING_JOBS} job(s) queued and not yet started; the restart re-queues them"
    fi
    if [ "$RUNNING_JOBS" -gt 0 ] && [ "$NEEDS_RESTART" -eq 0 ]; then
        ok "${RUNNING_JOBS} job(s) running, and they are safe: nothing will be restarted"
    elif [ "$RUNNING_JOBS" -gt 0 ] && [ "$DRAIN" -eq 0 ] && [ "$FORCE" -eq 0 ]; then
        die "${RUNNING_JOBS} job(s) are running, and the restart will kill them.
      Choose explicitly:
          --drain   stop admitting new jobs, wait for these to finish, then update
                    (up to ${DRAIN_TIMEOUT}s; a CASSCF run taking hours is normal here)
          --force   update now and accept losing them
      Nothing has been changed."
    fi

    if [ "$DRY_RUN" -eq 1 ]; then
        echo
        ok "dry run: every gate passed. Re-run without --dry-run to update."
        exit 0
    fi

    # --- from here on the deployment is being changed --------------------------
    step "backing up before changing anything (full: database + all of data/)"
    # The path is captured, not just printed, because every recovery instruction
    # below needs to name it. Telling an operator mid-failure to "restore from the
    # backup" without saying which directory is how a backup goes unused.
    BACKUP_PATH=""
    BACKUP_LOG="$(mktemp)"
    if bash scripts/backup.sh --full 2>&1 | tee "$BACKUP_LOG"; then
        BACKUP_PATH="$(sed -nE 's/^\[backup [^]]*\] wrote (.*)$/\1/p' "$BACKUP_LOG" | tail -n1)"
        rm -f "$BACKUP_LOG"
        ok "full backup taken${BACKUP_PATH:+ -- ${BACKUP_PATH}}"
    else
        rm -f "$BACKUP_LOG"
        die "backup failed -- refusing to update without one.
      This is the only thing that can undo a schema change or a lost job."
    fi

    # What to tell someone whose update has just gone wrong. --rollback is only
    # ever the right answer for a non-destructive change that actually moved the
    # checkout; the two other cases used to be handed the same advice, and both
    # times it was advice that cannot work. See this tracker's Phase 2.
    recovery_advice() {
        echo
        echo "  the pre-update backup is at: ${BACKUP_PATH:-<the directory scripts/backup.sh printed above>}"
        if [ "$DESTRUCTIVE" -eq 1 ]; then
            echo "  ${YEL}Do not reach for --rollback here.${RST} The report above found this"
            echo "  change destructive, and --rollback moves code and nothing else: it"
            echo "  would leave the old code running against the already-migrated"
            echo "  database. Restore instead, and read that script's own warnings first:"
            echo "      scripts/restore.sh ${BACKUP_PATH:-<backup dir>}"
        elif [ "$REBUILD_ONLY" -eq 1 ]; then
            echo "  ${YEL}--rollback cannot help here.${RST} The checkout never moved -- only"
            echo "  the build was behind -- so there is no previous commit recorded for it"
            echo "  to return to. Check out the earlier commit by hand and rebuild, or"
            echo "  restore with: scripts/restore.sh ${BACKUP_PATH:-<backup dir>}"
        else
            echo "  this change was not reported destructive, so the code can go back:"
            echo "      scripts/update.sh --rollback"
        fi
    }

    # One place that writes ${UPDATE_LOG}, so the health verb and the rebuild-only
    # suppression cannot drift apart between the two exits that record an update.
    #
    # Records REPORT_FROM as the previous commit, not the checkout's old HEAD.
    # Those differ exactly when this work is doing its job: with a stamped image
    # running behind the checkout, HEAD had moved to a commit that was never
    # deployed, and --rollback reads this file to decide where to put the
    # deployment back to. Returning it to a commit that never served traffic is
    # the same class of mistake as returning it to one that never came up healthy.
    record_update() {
        local verb="$1"
        if [ "$REBUILD_ONLY" -eq 1 ]; then
            info "no ${UPDATE_LOG} entry: the checkout did not move, so an entry would"
            info "name ${TARGET_SHA:0:12} as both the new and the previous commit and"
            info "--rollback would resolve it to a no-op."
            return 0
        fi
        printf '%s %s %s %s\n' "$verb" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$TARGET_SHA" "$REPORT_FROM" >> "$UPDATE_LOG"
    }

    psql_stack() { "${COMPOSE[@]}" exec -T postgres psql -At -U "$PGUSER_VAL" -d "$PGDB_VAL" "$@"; }

    DRAINED=0
    IN_MAINTENANCE=0

    # --maintenance closes the app to everyone but admins and drops every
    # other session, immediately before the stack is recreated.
    #
    # The ORDER is the whole point, and the obvious order is wrong. Locking
    # people out first and then draining means they are locked out for the
    # entire drain -- and a drain here waits for CASSCF runs, so
    # QC_AGENT_DRAIN_TIMEOUT defaults to four hours. Users would be shut out of
    # the app for half a day while waiting for their own jobs to finish. So:
    # pause admission (people keep working), wait for the drain, and only then
    # lock the doors, seconds before the restart that would break their session
    # anyway.
    #
    # Both halves are undone by the same EXIT trap as the drain, so a failure,
    # an abort or a Ctrl-C cannot leave a deployment locked with nothing
    # scheduled to unlock it.
    enter_maintenance() {
        [ "$MAINTENANCE" -eq 1 ] || return 0
        psql_stack -c "INSERT INTO app_config (key, value) VALUES ('maintenance_mode', 'true'::jsonb)
                       ON CONFLICT (key) DO UPDATE SET value='true'::jsonb, updated_at=now()" >/dev/null \
            || die "could not enter maintenance mode -- refusing to restart without it."
        IN_MAINTENANCE=1
        ok "maintenance mode on: non-admins get a 503 until this finishes"

        # One key per user, so this is every logged-in session. redis-cli's
        # --scan is used rather than KEYS because KEYS blocks the server, and
        # this runs against a live deployment.
        local killed
        killed="$("${COMPOSE[@]}" exec -T redis sh -c \
            'redis-cli --scan --pattern "qc_agent:session:active:*" | xargs -r redis-cli DEL' \
            2>/dev/null | tail -n1 || echo 0)"
        ok "logged out ${killed:-0} session(s); they see the maintenance screen, not a login loop"
    }

    leave_maintenance() {
        [ "$IN_MAINTENANCE" -eq 1 ] || return 0
        psql_stack -c "DELETE FROM app_config WHERE key='maintenance_mode'" >/dev/null 2>&1 || true
        IN_MAINTENANCE=0
        ok "maintenance mode off"
    }

    restore_admission() {
        [ "$DRAINED" -eq 1 ] || return 0
        psql_stack -c "DELETE FROM app_config WHERE key='job_admission_paused'" >/dev/null 2>&1 || true
        DRAINED=0
        ok "job admission restored"
    }
    trap 'leave_maintenance; restore_admission' EXIT

    if [ "$DRAIN" -eq 1 ] && [ "$INFLIGHT" -gt 0 ] && [ "$NEEDS_RESTART" -eq 1 ]; then
        step "draining"
        # Its own flag rather than max_concurrent_jobs_total=0. The cap is an
        # admin-facing setting whose API refuses any value <= 0, so writing 0
        # here meant this script and the admin console disagreed about what a
        # legal value was -- and a job queued behind it reported "waiting for
        # a free job slot", which says nothing about why the queue is stopped
        # or that it will restart by itself.
        psql_stack -c "INSERT INTO app_config (key, value) VALUES ('job_admission_paused', 'true'::jsonb)
                       ON CONFLICT (key) DO UPDATE SET value='true'::jsonb, updated_at=now()" >/dev/null \
            || die "could not stop job admission -- not draining blind."
        DRAINED=1
        ok "new jobs are no longer admitted (they queue as pending)"
        info "waiting for ${INFLIGHT} in-flight job(s); Ctrl-C is safe, admission is restored on exit"
        WAITED=0
        while [ "$WAITED" -lt "$DRAIN_TIMEOUT" ]; do
            RUNNING="$(python3 - data/jobs <<'PY'
import json, os, sys
root = sys.argv[1]
n = 0
for name in (os.listdir(root) if os.path.isdir(root) else []):
    p = os.path.join(root, name, "status.json")
    if not os.path.isfile(p):
        continue
    try:
        with open(p) as fh:
            if json.load(fh).get("status") == "running":
                n += 1
    except Exception:
        pass
print(n)
PY
    )"
            [ "$RUNNING" -eq 0 ] && break
            printf '\r  .. %s job(s) still running, waited %ss   ' "$RUNNING" "$WAITED"
            sleep 30
            WAITED=$((WAITED + 30))
        done
        echo
        if [ "${RUNNING:-0}" -ne 0 ]; then
            restore_admission
            die "still ${RUNNING} job(s) running after ${DRAIN_TIMEOUT}s. Admission restored;
      nothing was updated. Wait longer (QC_AGENT_DRAIN_TIMEOUT=<seconds>), or use
      --force if you have decided to lose them."
        fi
        ok "drained"
    fi

    if [ "$REBUILD_ONLY" -eq 1 ]; then
        step "leaving the checkout where it is"
        ok "already at $(git rev-parse --short HEAD); this update is a rebuild"
    else
        step "moving the checkout to ${TARGET_SHA:0:12}"
        CURRENT_BRANCH="$(git rev-parse --abbrev-ref HEAD)"
        if [ "$CURRENT_BRANCH" = "HEAD" ]; then
            git checkout --detach --quiet "$TARGET_SHA"
        else
            git merge --ff-only --quiet "$TARGET_SHA"
        fi
        ok "checked out $(git rev-parse --short HEAD)"
    fi

    if [ "$NEEDS_RESTART" -eq 0 ]; then
        step "not restarting anything"
        ok "this change touches only documentation, so the running stack is already correct"
        leave_maintenance
        restore_admission
        trap - EXIT
        # Healthy by construction: nothing was restarted, so whatever was serving
        # traffic a moment ago still is.
        record_update updated
        echo
        echo "${GRN}updated${RST} ${REPORT_FROM:0:12} -> ${TARGET_SHA:0:12} (documentation only, no restart)"
        [ "$REBUILD_ONLY" -eq 1 ] || echo "  recorded in ${UPDATE_LOG}; roll back with: scripts/update.sh --rollback"
        exit 0
    fi

    step "rebuilding"
    # The stamp the api image will carry, read back by deployed_commit() on
    # every later run. Exported rather than passed with --build-arg so it
    # reaches the build through docker-compose.yml's own args block, which is
    # where the default (`unknown`) lives too.
    export QC_AGENT_BUILD_COMMIT="$TARGET_SHA"

    # Build, then install the bundle, then bring the stack up -- in that order.
    # This used to be a single `up -d --build` after the frontend build, but
    # the frontend build was a separate host `npm run build` that could be
    # skipped. Now the bundle comes out of the image the build just produced,
    # so the image has to exist first, and frontend/dist has to be on disk
    # before nginx is recreated against it.
    if ! "${COMPOSE[@]}" build; then
        echo "${RED}update: docker compose build failed. Nothing was recreated.${RST}" >&2
        exit 1
    fi
    ok "images built at ${TARGET_SHA:0:12}"

    bash scripts/extract_frontend.sh "$TARGET_SHA" \
        || die "the frontend bundle could not be installed; nothing was recreated."

    # Maintenance starts HERE, not before the build.
    #
    # It was before the build to begin with, and a real run showed why that is
    # wrong: the image build takes about ten minutes, and it changes nothing
    # about the deployment that is still running. Entering maintenance first
    # locked every user out for the build AND the restart, when only the
    # restart makes the app unusable. Everything above this line -- the backup,
    # the report, the build, installing the bundle -- happens with the
    # deployment up and people working.
    #
    # The lockout is now the recreate plus the health check: about ninety
    # seconds, which is the api container's start period.
    enter_maintenance

    if ! "${COMPOSE[@]}" up -d; then
        echo "${RED}update: compose up failed. The stack may be partly down.${RST}" >&2
        echo "  check: ${COMPOSE[*]} ps" >&2
        recovery_advice >&2
        exit 1
    fi

    step "verifying"

    if [ -n "${QC_AGENT_UPDATE_HEALTH_URL:-}" ]; then
        HEALTH_URLS="$QC_AGENT_UPDATE_HEALTH_URL"
    else
        HEALTH_URLS="$(health_urls)"
    fi
    # Resolved here rather than at the top of the script: `compose port` needs a
    # container to ask about, and the one that will answer the health check is
    # the one that has just been brought up.
    BASE_URL="${HEALTH_URLS%% *}"
    info "health check against: ${HEALTH_URLS}"

    # Read the stamp back off what is now running. `compose up -d --build`
    # recreates a container whose image changed, but that is a behaviour of
    # compose rather than a promise this script can make, and the failure mode if
    # it does not is silent: the build succeeds, the old container keeps serving
    # the old code, and the only visible symptom is that the next update says the
    # deployment is still behind. Checking here names it at the moment it happens.
    POST_SHA="$(deployed_commit)"
    if [ -n "$POST_SHA" ] && [ "$POST_SHA" != "$TARGET_SHA" ]; then
        warn "the api container is still running ${POST_SHA:0:12}, not ${TARGET_SHA:0:12}."
        warn "The image was rebuilt but the container was not replaced. Force it:"
        warn "    ${COMPOSE[*]} up -d --force-recreate api"
    elif [ -z "$POST_SHA" ]; then
        warn "the api container reports no build stamp after the rebuild. Later runs"
        warn "will treat this deployment as stale and rebuild it again rather than"
        warn "wrongly reporting it current, but the stamp is worth looking into."
    fi

    HEALTHY=0
    qc_wait_for_health 300 "$HEALTH_URLS" && HEALTHY=1 || HEALTH_RC=$?
    if [ "$HEALTHY" -eq 1 ]; then
        BASE_URL="$QC_HEALTH_URL"
        ok "healthy at ${BASE_URL}"
    elif [ "${HEALTH_RC:-1}" -eq 2 ]; then
        warn "a container stopped while coming back up: ${QC_STOPPED_SERVICES}"
        # shellcheck disable=SC2086  # one argument per stopped service
        "${COMPOSE[@]}" logs --tail 25 ${QC_STOPPED_SERVICES} 2>&1 | sed 's/^/      /' || true
        recovery_advice
    else
        warn "not healthy after 300s."
        warn "Check ${COMPOSE[*]} logs api -- and note the api healthcheck allows a"
        warn "90s start_period, so a slow first import is not automatically a failure."
        "${COMPOSE[@]}" logs --tail 25 api 2>&1 | sed 's/^/      /' || true
        recovery_advice
    fi

    leave_maintenance
    restore_admission
    trap - EXIT

    # Recorded WITH the verdict, and only after it is known. The old code appended
    # an `updated` line before the health check was considered at all, so a
    # deployment that never came up was written down as the good commit a later
    # --rollback would return to.
    if [ "$HEALTHY" -eq 1 ]; then
        record_update updated
    else
        record_update unhealthy
    fi

    echo
    if [ "$HEALTHY" -eq 1 ]; then
        echo "${GRN}updated${RST} ${REPORT_FROM:0:12} -> ${TARGET_SHA:0:12}"
        if [ "$REBUILD_ONLY" -eq 1 ]; then
            echo "  the checkout was already there; the build now matches it."
        else
            echo "  recorded in ${UPDATE_LOG}; roll back with: scripts/update.sh --rollback"
        fi
    else
        echo "${YEL}updated, but it did not come up healthy${RST} ${REPORT_FROM:0:12} -> ${TARGET_SHA:0:12}"
        [ "$REBUILD_ONLY" -eq 1 ] || echo "  recorded in ${UPDATE_LOG} as unhealthy, so --rollback will not return here."
    fi
    echo "  hard-reload your browser tab if the frontend changed."
}

main "$@"

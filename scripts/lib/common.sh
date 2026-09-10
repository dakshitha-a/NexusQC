#!/usr/bin/env bash
# Shared helpers for the two scripts that stand up and advance a deployment:
# scripts/install.sh and scripts/update.sh.
#
# WHY THIS EXISTS, AND WHY IT COVERS ONLY TWO SCRIPTS
# ---------------------------------------------------
# Seven scripts under scripts/ carried their own copy of the colour block and
# their own die/ok/info/warn/step. That is survivable for prose, but it stopped
# being survivable once the copies started disagreeing about behaviour rather
# than appearance: install.sh emitted colour into redirected logs because it
# alone lacked the `[ -t 1 ]` guard its siblings had, install.sh had a preflight
# and update.sh had none, and update.sh knew how to find a deployment that
# publishes on a non-default port while install.sh hardcoded 8443.
#
# Only install.sh and update.sh source this. release.sh, check_public_safe.sh
# and check_destructive.sh gate publication to the public remote and are not
# worth destabilising for tidiness; extract_frontend.sh and install_updater.sh
# are small and already correct. Unifying those five is logged in the tracker
# as its own piece of work.
#
# TWO CONSTRAINTS ON CALLERS
# --------------------------
# 1. install.sh's prologue CANNOT source this. Piped from curl there is no
#    checkout on disk yet, and the prologue runs under dash. Everything above
#    install.sh's `exec` stays self-contained POSIX; this file is bash and is
#    sourced only after that point.
# 2. update.sh must source this BEFORE entering main(), not inside it.
#    update.sh fast-forwards the very checkout it is running from, and a
#    `source` executed after that would read a different file than the one the
#    script was written against -- the same hazard update.sh's main() wrapper
#    exists to prevent for its own text.
#
# Callers configure it with two variables:
#     QC_PREFIX      what die() prefixes its message with ("install"/"update")
#     QC_COMPOSE     an array holding the compose command with its -f flags
# and optionally QC_STEP_TOTAL, which turns on "[3/9]" numbering in step().

# --- appearance --------------------------------------------------------------
# Guarded, unlike the copy install.sh used to carry. An install redirected to a
# log file is the normal way someone captures one to send to you, and escape
# sequences all through it help nobody. NO_COLOR is the cross-tool convention
# (https://no-color.org) and costs one test to honour.
if [ -t 1 ] && [ -z "${NO_COLOR:-}" ]; then
    RED=$'\033[31m'; GRN=$'\033[32m'; YEL=$'\033[33m'
    DIM=$'\033[2m';  BLD=$'\033[1m';  RST=$'\033[0m'
else
    RED=''; GRN=''; YEL=''; DIM=''; BLD=''; RST=''
fi

# Four variables in this file are set here and read only by the script that
# sourced it -- QC_DIED and QC_STEP_NAME by its exit trap, QC_HEALTH_URL and
# QC_STOPPED_SERVICES by whoever called the health wait. shellcheck cannot see
# across a `source`, so each carries its own disable rather than one file-wide
# directive that would also hide a genuinely unused variable added later.

# --- reporting ---------------------------------------------------------------
# QC_STEP_NAME is what the failure trap reports when something dies. Without it
# an unexpected exit says only that the script stopped, which is precisely the
# situation someone needs the most help in.
# shellcheck disable=SC2034  # read by the caller's exit trap
QC_STEP_NAME="starting up"
QC_STEP_INDEX=0
# shellcheck disable=SC2034  # read by the caller's exit trap
QC_DIED=0

# shellcheck disable=SC2034  # QC_DIED is read by the caller's exit trap
die()  { QC_DIED=1; echo "${RED}${QC_PREFIX:-install}: $*${RST}" >&2; exit 1; }
ok()   { echo "${GRN}  ok${RST}  $*"; }
info() { echo "${DIM}  ..${RST}  $*"; }
warn() { echo "${YEL}  !!${RST}  $*"; }

step() {
    # shellcheck disable=SC2034  # read by the caller's exit trap
    QC_STEP_NAME="$1"
    QC_STEP_INDEX=$(( QC_STEP_INDEX + 1 ))
    local label="$1"
    [ -n "${QC_STEP_TOTAL:-}" ] && label="[${QC_STEP_INDEX}/${QC_STEP_TOTAL}] $1"
    # Pad the rule to a fixed overall width instead of appending a fixed number
    # of dashes, so a long step title does not produce a ragged banner or wrap
    # on an 80-column terminal.
    local width=72 pad=""
    local n=$(( width - ${#label} - 5 ))
    [ "$n" -lt 3 ] && n=3
    pad="$(printf '%*s' "$n" '' | tr ' ' '-')"
    echo
    echo "${BLD}--- ${label} ${pad}${RST}"
}

banner() {
    # The same rule as step(), without a number and without advancing the
    # counter. The closing summary is not one of the steps it counts -- printing
    # it through step() is what produced a cheerful "[11/10] done".
    # shellcheck disable=SC2034  # read by the caller's exit trap
    QC_STEP_NAME="$1"
    local width=72 n pad
    n=$(( width - ${#1} - 5 )); [ "$n" -lt 3 ] && n=3
    pad="$(printf '%*s' "$n" '' | tr ' ' '-')"
    echo
    echo "${BLD}--- ${1} ${pad}${RST}"
}

# --- questions ---------------------------------------------------------------
# Every prompt goes through these two, and both handle EOF rather than letting
# it kill the script. A bare `read` returns non-zero at end of input, and under
# `set -e` that exits mid-question with nothing printed at all -- which is what
# Ctrl-D, a closed terminal, or a pipe that ran out used to do to install.sh.
ask() {
    # $1 = prompt, $2 = optional default. Answer lands in REPLY.
    local prompt="$1" default="${2:-}"
    [ -n "$default" ] && prompt="${prompt}[${default}] "
    printf '%s' "$prompt" >&2
    if ! read -r REPLY; then
        echo >&2
        die "no more input (end of file) while asking: $1
  Nothing has been changed by this question. Re-run from a terminal, or use
  --non-interactive with the environment variables --help describes."
    fi
    # An `if`, not `[ -z ... ] && ...`. As the last command of a function that
    # form returns the test's own status, so a non-empty answer -- which is to
    # say almost every answer -- made ask() return 1 and `set -e` killed the
    # caller on the spot. The installer died immediately after the first
    # question anyone actually answered.
    if [ -z "$REPLY" ]; then
        REPLY="$default"
    fi
    return 0
}

ask_yn() {
    # $1 = prompt, $2 = default (y/n). Sets ASK_YN_OK to 1/0.
    # Answers are re-asked rather than guessed: "maybe" meaning no is the kind
    # of thing that gets noticed only after the install has done the opposite.
    local def="${2:-n}" suffix="[y/N]" reply
    [ "$def" = "y" ] && suffix="[Y/n]"
    while :; do
        printf '%s %s ' "$1" "$suffix" >&2
        if ! read -r reply; then
            echo >&2
            die "no more input (end of file) while asking: $1
  Nothing has been changed by this question. Re-run from a terminal, or use
  --non-interactive with the environment variables --help describes."
        fi
        reply="${reply:-$def}"
        case "$reply" in
            [yY]|[yY][eE][sS]) ASK_YN_OK=1; return 0 ;;
            [nN]|[nN][oO])     ASK_YN_OK=0; return 0 ;;
            *) warn "please answer y or n." ;;
        esac
    done
}

# --- .env editing ------------------------------------------------------------
envset() {
    # Idempotently sets KEY=VALUE in .env, appending if the key is absent.
    # Replaces an active line if one exists; otherwise an env.example-style
    # commented-out placeholder for the same key (`# KEY=...`), so a value the
    # installer fills in does not leave both the commented example and the real
    # value sitting in the file; otherwise appends.
    #
    # The escaping is not decorative. sed treats `&` in a replacement as "the
    # whole match" and `\` as an escape, and both branches below use a
    # delimiter that can appear in a real value -- a filesystem path may
    # legitimately contain `#` or `|`. A password from `openssl rand -hex`
    # cannot contain any of them, but a path typed at a prompt can, and the
    # failure is a silently corrupted .env rather than an error.
    local key="$1" value="$2" escaped
    escaped="$value"
    escaped="${escaped//\\/\\\\}"
    escaped="${escaped//&/\\&}"
    escaped="${escaped//|/\\|}"
    escaped="${escaped//\#/\\#}"
    if grep -qE "^${key}=" .env 2>/dev/null; then
        sed -i -E "s#^${key}=.*#${key}=${escaped}#" .env
    elif grep -qE "^#[[:space:]]*${key}=" .env 2>/dev/null; then
        # A different delimiter here on purpose: this pattern contains a
        # literal `#`, which would close an s#...# command mid-pattern. The
        # value has both characters escaped above, so either delimiter is safe
        # for the replacement half.
        sed -i -E "s|^#[[:space:]]*${key}=.*|${key}=${escaped}|" .env
    else
        printf '%s=%s\n' "$key" "$value" >> .env
    fi
}

envget() {
    # $1 = file, $2 = key. Last assignment wins, quotes stripped.
    local file="$1" key="$2"
    [ -f "$file" ] || return 0
    sed -nE "s/^[[:space:]]*${key}=(.*)$/\1/p" "$file" | tail -n1 | sed -E 's/^"(.*)"$/\1/'
}

# --- validation --------------------------------------------------------------
valid_ipv4() {
    # A real check, not a shape check. This guards the address that goes into
    # the certificate's subjectAltName as `IP:<value>`, and openssl rejects
    # anything that is not an address -- so a hostname typed at the "IP
    # address:" prompt used to end the install with no output whatsoever.
    local ip="$1" o
    case "$ip" in
        *[!0-9.]*|*..*|.*|*.) return 1 ;;
    esac
    [ "$(printf '%s\n' "$ip" | tr -cd '.' | wc -c)" -eq 3 ] || return 1
    for o in ${ip//./ }; do
        [ -n "$o" ] || return 1
        [ "$o" -le 255 ] 2>/dev/null || return 1
    done
    return 0
}

# --- preflight ---------------------------------------------------------------
# Everything here answers a question that otherwise gets answered ten or twenty
# minutes later, by a failure whose message names the symptom rather than the
# cause. Each one names the fix.

require_tools() {
    local tool missing=()
    for tool in "$@"; do
        command -v "$tool" >/dev/null 2>&1 || missing+=("$tool")
    done
    if [ "${#missing[@]}" -gt 0 ]; then
        die "not on PATH: ${missing[*]}
  Debian/Ubuntu:  sudo apt install ${missing[*]}
  RHEL/Fedora:    sudo dnf install ${missing[*]}"
    fi
}

require_docker() {
    docker compose version >/dev/null 2>&1 \
        || die "docker compose (v2, the 'docker compose' subcommand) is required.
  The older standalone 'docker-compose' will not do: this project uses v2
  syntax throughout. See https://docs.docker.com/compose/install/"

    # `command -v docker` passing proves only that the CLI is installed. The
    # daemon being stopped, or this user not being in the docker group, is the
    # single most common way a first install fails -- and it fails at the build,
    # several questions in, with a permission error that reads like a bug.
    # `timeout` because a wedged daemon makes `docker info` hang rather than
    # fail, and hanging with no output is worse than either outcome.
    local out rc
    out="$(timeout 15 docker info 2>&1)"; rc=$?
    if [ "$rc" -ne 0 ]; then
        case "$out" in
            *"permission denied"*)
                die "this user cannot talk to the docker daemon.
  Add yourself to the docker group, then log out and back in (or run
  \`newgrp docker\` in this shell) and re-run:
      sudo usermod -aG docker $(id -un)" ;;
            *"Cannot connect"*|*"Is the docker daemon running"*)
                die "the docker daemon is not running.
      sudo systemctl start docker" ;;
            *)
                [ "$rc" -eq 124 ] && die "the docker daemon did not respond within 15s.
  It may be starting, or wedged. Check: systemctl status docker"
                die "docker is not usable here:
$(printf '%s\n' "$out" | sed 's/^/      /' | head -5)" ;;
        esac
    fi
}

require_disk() {
    # $1 = path to check, $2 = required GB, $3 = what it is for.
    # Reported as a measurement rather than a verdict: someone who knows their
    # docker root is on another filesystem needs the number, not a refusal.
    local path="$1" need="$2" what="$3" avail
    avail="$(df -BG --output=avail "$path" 2>/dev/null | tail -n1 | tr -dc '0-9')"
    [ -n "$avail" ] || { info "could not measure free space on ${path}"; return 0; }
    if [ "$avail" -lt "$need" ]; then
        warn "${path} has ${avail} GB free; ${what} needs about ${need} GB."
        ASK_YN_OK=1
        [ "${QC_NONINTERACTIVE:-0}" -eq 1 ] || ask_yn "  Continue anyway?" n
        [ "$ASK_YN_OK" -eq 1 ] || die "stopped -- free some space and re-run."
    else
        ok "${avail} GB free on ${path} (${what} needs about ${need})"
    fi
}

require_port_free() {
    # $1 = "addr:port". Bound already means `compose up` fails at the very end,
    # after the build, with a message about an address already in use that says
    # nothing about which other thing is holding it.
    local hp="$1"
    command -v ss >/dev/null 2>&1 || return 0
    if ss -ltn 2>/dev/null | awk '{print $4}' | grep -qxF "$hp"; then
        die "${hp} is already in use.
  Another service -- very possibly another NexusQC deployment -- is listening
  there. Stop it, or publish this one somewhere else. \`ss -ltnp\` names the
  process holding it."
    fi
}

require_data_writable() {
    # An older, root-running image left data/ owned by root. The container now
    # runs as APP_UID:APP_GID and cannot write it, and the symptom is a
    # PermissionError on the first molecule lookup -- long after the install
    # said it had succeeded.
    [ -d data ] || return 0
    [ -w data ] && return 0
    die "data/ exists but is not writable by you (uid $(id -u)).
  It was most likely created by an older image running as root. Take it back:
      sudo chown -R $(id -u):$(id -g) data
  Nothing in it is lost by doing so."
}

# --- finding and waiting for the deployment ----------------------------------
# Where to knock to see whether the deployment is up. Asked of compose rather
# than assumed: a deployment is free to publish nginx on a different host port,
# and this project's own docker-compose.override.yml.example does exactly that.
# Hardcoding 8443 once made update.sh report a perfectly healthy stack as never
# having come up. install.sh writes its own port and so was not wrong yet, but
# it had no protection at all if the override were hand-edited afterwards.
#
# Produces a space-separated list rather than one URL: a deployment may publish
# on loopback, on a routable address, or on both, and the point is to find the
# stack rather than to insist on a particular way of reaching it.
health_urls() {
    local mapped="" port="" out="" hp=""
    mapped="$("${QC_COMPOSE[@]}" port nginx 8443 2>/dev/null || true)"
    port="$(printf '%s\n' "$mapped" | head -n1 | sed -nE 's/.*:([0-9]+)$/\1/p')"
    out="https://127.0.0.1:${port:-8443}"
    # Plus whatever else compose says it published, minus the wildcard binds
    # (nothing to connect to) and loopback (already first in the list).
    while IFS= read -r hp; do
        [ -n "$hp" ] || continue
        case "$hp" in 0.0.0.0:*|\[::\]:*|127.0.0.1:*) continue ;; esac
        out="${out} https://${hp}"
    done <<EOF
${mapped}
EOF
    printf '%s\n' "$out"
}

# Any service that has stopped. A container in this stack that has exited has
# failed: all four are long-running, none legitimately completes. Catching it
# turns a five-minute silence into an immediate, specific answer.
qc_stopped_services() {
    "${QC_COMPOSE[@]}" ps -a --format '{{.Service}} {{.State}}' 2>/dev/null \
        | awk '$2 == "exited" || $2 == "dead" { print $1 }'
}

qc_service_states() {
    # "api: healthy, postgres: healthy, ..." for the progress line. Health is
    # blank for services that declare no healthcheck (nginx), so fall back to
    # the run state rather than printing an empty field.
    "${QC_COMPOSE[@]}" ps -a --format '{{.Service}} {{.State}} {{.Health}}' 2>/dev/null \
        | awk '{ s = ($3 == "" ? $2 : $3); printf "%s%s:%s", (NR>1 ? " " : ""), $1, s }'
}

# Wait for the stack, saying so while it waits.
#
# The loop this replaces printed one line and then nothing for up to five
# minutes, could not tell "still importing" from "the container exited thirty
# seconds ago", and gave the same answer either way. The api healthcheck alone
# allows a 90s start_period, so a long silence here is normal and a person
# watching it has no way to know that.
#
# Sets QC_HEALTH_URL on success. Returns 0 healthy, 1 timed out, 2 a container
# exited -- the caller decides what each is worth, because for install.sh a
# dead stack means skipping the admin bootstrap and for update.sh it does not.
qc_wait_for_health() {
    local timeout="${1:-300}" urls="$2"
    local start now elapsed u stopped last_note=0 spin=0
    local frames="|/-\\"
    start="$(date +%s)"
    QC_HEALTH_URL=""

    while :; do
        for u in $urls; do
            if curl -fsS -k --max-time 5 "${u}/api/health" >/dev/null 2>&1; then
                # shellcheck disable=SC2034  # the caller reads this
                QC_HEALTH_URL="$u"
                [ -t 1 ] && printf '\r\033[K'
                return 0
            fi
        done

        stopped="$(qc_stopped_services)"
        if [ -n "$stopped" ]; then
            [ -t 1 ] && printf '\r\033[K'
            # shellcheck disable=SC2034  # the caller reads this
            QC_STOPPED_SERVICES="$stopped"
            return 2
        fi

        now="$(date +%s)"; elapsed=$(( now - start ))
        [ "$elapsed" -ge "$timeout" ] && { [ -t 1 ] && printf '\r\033[K'; return 1; }

        if [ -t 1 ]; then
            spin=$(( (spin + 1) % 4 ))
            printf '\r\033[K%s  %s  %ds elapsed, up to %ds  %s' \
                "${DIM}" "${frames:$spin:1}" "$elapsed" "$timeout" \
                "$(qc_service_states)${RST}"
        elif [ $(( elapsed - last_note )) -ge 30 ]; then
            # No terminal to rewrite a line on, so a periodic note instead --
            # a redirected install log should still show progress rather than a
            # five-minute gap that reads like a hang.
            last_note="$elapsed"
            info "still waiting (${elapsed}s): $(qc_service_states)"
        fi
        sleep 3
    done
}

qc_elapsed_human() {
    # $1 = seconds. "4m 12s", or "38s".
    local s="$1"
    if [ "$s" -ge 60 ]; then
        printf '%dm %ds' $(( s / 60 )) $(( s % 60 ))
    else
        printf '%ds' "$s"
    fi
}

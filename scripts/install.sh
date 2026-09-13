#!/usr/bin/env bash
# First-time setup for a NexusQC deployment: checks this host can run one,
# generates secrets, picks a network exposure, detects (or asks for) ORCA and
# BAGEL, checks the language model, builds the stack and creates the first
# admin account.
#
# TWO MODES, ONE FILE
# -------------------
# Run from inside a checkout, it installs that checkout. Piped from curl there
# is no checkout yet, so it clones one and re-runs itself from inside it:
#
#     curl -fsSL https://raw.githubusercontent.com/dakshitha-a/NexusQC/main/scripts/install.sh | sh
#
# A separate bootstrap file would be a second thing to keep in step with this
# one, which is why the prologue below lives here instead.
#
# Only the prologue is ever executed by `sh`. On Debian and Ubuntu that is
# dash, so everything above the `exec` is strictly POSIX: `set -eu` rather than
# `set -euo pipefail` (dash exits on the unknown -o option before reaching line
# two), `$0` rather than ${BASH_SOURCE[0]}, no arrays, no [[ ]], no $'\033'.
# Everything after the `exec` runs from a real file under bash and may use all
# of them, including scripts/lib/common.sh -- which the prologue cannot source,
# because piped from curl there is no checkout on disk to source it from.
# Getting this wrong is not subtle-but-survivable: it kills the one-liner on
# every Debian-family machine, which is most of them.
#
# Wherever this checkout ends up is where data/ (jobs, KB, uploads, the
# molecule cache) will live, as a bind mount under docker-compose.yml -- there
# is no separate "data directory" setting, only where you put the clone.
#
# WHAT THIS DOES, IN ORDER
# The numbers below are the ones printed on screen, so a report of "it stopped
# at step 6" names something findable. Keep them in step with the `step` calls.
#    1. checks this host can actually run it: tools, a reachable docker daemon,
#       disk headroom, a free port, a writable data/
#    2. confirms the install location and what will live there
#    3. writes .env with fresh secrets and this host's uid/gid
#    4. asks how the stack should be reachable and mints a matching TLS
#       certificate (localhost is always on; anything else is opt-in)
#    5. detects ORCA/BAGEL, or asks for their paths, or lets you skip either,
#       and offers the optional DMRG backend
#    6. checks the language model is reachable and pulled
#    7. builds the images and takes frontend/dist out of the built one
#    8. starts everything and waits for it, saying so while it waits
#    9. creates the first admin account
#   10. optionally installs the host service that lets the admin panel update
#       this deployment itself
# then prints where to reach it and what to do next.
#
# Usage:
#     scripts/install.sh [--dir=PATH] [--repo=URL] [--bind=MODE]
#                        [--non-interactive] [--pull-model] [--install-updater]
#                        [--force-override] [--help]
#
# Safe to re-run: if .env already exists, you are asked whether to keep it
# (and just make sure the stack is up) or start over. Nothing here touches
# an already-populated data/ directory.
set -eu

# --- bootstrap: a checkout, or a pipe? --------------------------------------
# `[ -f "$0" ]` is the first gate rather than a sentinel probe alone. Piped,
# $0 is "sh" or "bash" and names no file, which is a cleaner signal than
# testing whether ../docker-compose.yml happens to exist relative to the
# current directory -- that alternative misreads "run from a subdirectory of
# some unrelated checkout" as an in-place install.
# Defined up here, in POSIX form, because --help has to be answerable before
# the clone below -- printing usage is not a reason to put a repository on
# someone's disk. The bash half calls this same function rather than carrying a
# second copy of the text that would drift from this one.
usage() {
    cat <<'USAGE'
usage: install.sh [--dir=PATH] [--repo=URL] [--bind=MODE] [--non-interactive]

  --dir     where to clone NexusQC when run from a pipe, default
            ~/apps/NexusQC. Ignored when run from inside a checkout.
            Also settable as NEXUSQC_DIR.
  --repo    which repository to clone, for a fork or a local path.
            Also settable as NEXUSQC_REPO.
  --bind    pre-answer the network question, skipping its prompt:
              localhost   this machine only (always on regardless)
              lan         also this host's LAN address
              tailscale   also this host's tailnet address
              both        LAN and tailnet

Unattended installs:

  --non-interactive   ask nothing. Requires --bind, and takes the first admin
                      account from the environment:
                        NEXUSQC_ADMIN_EMAIL      NEXUSQC_ADMIN_USERNAME
                        NEXUSQC_ADMIN_FIRSTNAME  NEXUSQC_ADMIN_LASTNAME
                        NEXUSQC_ADMIN_PASSWORD
                      Everything expensive or host-modifying stays OFF unless
                      you ask for it by flag, so an unattended run cannot
                      quietly download a model or write a systemd unit.
  --pull-model        pull the chat model if it is not present.
  --install-updater   install the systemd --user service that lets the admin
                      panel run updates on this host.
  --force-override    replace an existing docker-compose.override.yml without
                      asking. That file is not tracked by git, so what it
                      holds cannot be recovered.

Run it with no arguments to be asked everything:

    curl -fsSL https://raw.githubusercontent.com/dakshitha-a/NexusQC/main/scripts/install.sh | sh

USAGE
}

for _arg in "$@"; do
    case "$_arg" in
        --help|-h) usage; exit 0 ;;
    esac
done

NEXUSQC_BOOTSTRAP_OK=0
if [ -f "$0" ]; then
    _self_dir=$(dirname "$0")
    if [ -f "${_self_dir}/../docker-compose.yml" ] && [ -f "${_self_dir}/../.env.example" ]; then
        NEXUSQC_BOOTSTRAP_OK=1
    fi
fi

if [ "$NEXUSQC_BOOTSTRAP_OK" -eq 0 ]; then
    # This host's /bin/sh may be dash; everything in this branch is POSIX.
    case "$(uname -s)" in
        Linux) ;;
        Darwin)
            echo "NexusQC's installer is Linux-only: it uses \`ip route get\`, \`hostname -f\`" >&2
            echo "and GNU sed, none of which behave the same on macOS. Deploy it on a Linux" >&2
            echo "host, or run the Docker stack by hand -- see docs/DEPLOYMENT.md." >&2
            exit 1 ;;
        *)
            echo "NexusQC's installer supports Linux only (this is $(uname -s))." >&2
            exit 1 ;;
    esac

    command -v git >/dev/null 2>&1 || {
        echo "NexusQC needs git to fetch itself." >&2
        echo "  Debian/Ubuntu:  sudo apt install git" >&2
        echo "  RHEL/Fedora:    sudo dnf install git" >&2
        exit 1
    }

    # --dir= and --repo= have to be understood here as well as below, because
    # this is where the clone happens and the bash side never sees a pipe.
    TARGET="${NEXUSQC_DIR:-$HOME/apps/NexusQC}"
    REPO="${NEXUSQC_REPO:-https://github.com/dakshitha-a/NexusQC.git}"
    for _arg in "$@"; do
        case "$_arg" in
            --dir=*)  TARGET="${_arg#--dir=}" ;;
            --repo=*) REPO="${_arg#--repo=}" ;;
        esac
    done

    if [ -d "$TARGET/.git" ]; then
        # Deliberately NOT `git pull`. A deployment only ever advances via
        # scripts/update.sh, which reports what an update will do, refuses on
        # a dirty tree and takes a full backup first. Silently fast-forwarding
        # a checkout from an install one-liner would route around all of it.
        echo "A NexusQC checkout already exists at ${TARGET}."
        echo "Leaving it where it is -- to advance an existing deployment, run:"
        echo "    cd ${TARGET} && scripts/update.sh"
        echo "Continuing into it so an unfinished install can be resumed."
    else
        echo "Cloning NexusQC into ${TARGET}"
        mkdir -p "$(dirname "$TARGET")"
        git clone --quiet "$REPO" "$TARGET" || {
            echo "clone failed: $REPO" >&2
            exit 1
        }
    fi

    [ -f "$TARGET/scripts/install.sh" ] || {
        echo "${TARGET} is not a NexusQC checkout (no scripts/install.sh)." >&2
        exit 1
    }

    # Reconnect stdin to the terminal, or every `read` below would consume the
    # remainder of this script off the pipe. Tested by opening /dev/tty rather
    # than with `[ -r /dev/tty ]`: with no controlling terminal the device node
    # still exists and is readable, so the permission test passes and the exec
    # then fails with the shell's own bare "cannot open" and nothing from us.
    if ( exec < /dev/tty ) 2>/dev/null; then
        exec bash "$TARGET/scripts/install.sh" "$@" < /dev/tty
    else
        exec bash "$TARGET/scripts/install.sh" "$@"
    fi
fi

# Someone typed `sh scripts/install.sh`. Re-exec under bash before the first
# bashism below, rather than failing three lines later with a syntax error.
[ -n "${BASH_VERSION:-}" ] || exec bash "$0" "$@"

# From here down bash is guaranteed and the file is on disk.
set -o pipefail

SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SELF_DIR/.." && pwd)"
cd "$REPO_ROOT"

# Colours, die/ok/info/warn/step, ask/ask_yn, envset, the preflight checks and
# the health wait. Shared with update.sh so the two cannot drift; see that
# file's header for why the prologue above could not use it.
# shellcheck source=scripts/lib/common.sh
source "${SELF_DIR}/lib/common.sh"
QC_PREFIX="install"
QC_COMPOSE=(docker compose)
QC_STEP_TOTAL=10

# --- arguments ---------------------------------------------------------------
# --dir and --repo were consumed by the prologue above (they decide where the
# clone lands, which has already happened by the time we get here). They are
# accepted and ignored rather than rejected, so the same command line works
# whether it arrived through the pipe or was typed inside a checkout.
BIND_MODE=""
QC_NONINTERACTIVE=0
WANT_PULL_MODEL=ask
WANT_UPDATER=ask
FORCE_OVERRIDE=0
for argument in "$@"; do
    case "$argument" in
        --dir=*|--repo=*) ;;
        --bind=*)          BIND_MODE="${argument#--bind=}" ;;
        --non-interactive) QC_NONINTERACTIVE=1 ;;
        --pull-model)      WANT_PULL_MODEL=yes ;;
        --install-updater) WANT_UPDATER=yes ;;
        --force-override)  FORCE_OVERRIDE=1 ;;
        --help|-h)         usage; exit 0 ;;
        *) die "unknown option: $argument  (try --help)" ;;
    esac
done
case "$BIND_MODE" in
    ""|localhost|lan|tailscale|both) ;;
    *) die "--bind must be localhost, lan, tailscale or both (got '$BIND_MODE')" ;;
esac

# Silence must not mean yes to anything expensive or host-modifying. Two of the
# questions below default to `y` when a person is there to see them -- pulling
# a model that is tens of gigabytes, and writing a systemd unit onto this host.
# Inheriting those defaults in an unattended run would mean a script in someone
# else's CI quietly does both.
if [ "$QC_NONINTERACTIVE" -eq 1 ]; then
    [ -n "$BIND_MODE" ] || die "--non-interactive needs --bind: there is nobody to ask where
  this deployment should be reachable. Use --bind=localhost for this machine only."
    for _v in NEXUSQC_ADMIN_EMAIL NEXUSQC_ADMIN_USERNAME NEXUSQC_ADMIN_FIRSTNAME \
              NEXUSQC_ADMIN_LASTNAME NEXUSQC_ADMIN_PASSWORD; do
        [ -n "${!_v:-}" ] || die "--non-interactive needs ${_v} in the environment.
  See --help for the full list; the first admin account cannot be guessed."
    done
    [ "${#NEXUSQC_ADMIN_PASSWORD}" -ge 8 ] || die "NEXUSQC_ADMIN_PASSWORD must be at least 8 characters."
    [ "$WANT_PULL_MODEL" = "ask" ] && WANT_PULL_MODEL=no
    [ "$WANT_UPDATER" = "ask" ]    && WANT_UPDATER=no
fi

# Every question below is a bare `read`. Piped from curl the prologue hands us
# /dev/tty so those still work, but where there is no terminal at all -- cron,
# a CI runner, a container build -- there is nothing to read from. Say so here,
# while there is still nothing to clean up, and name the way to do it anyway.
if ! [ -t 0 ] && [ "$QC_NONINTERACTIVE" -eq 0 ]; then
    die "no terminal to ask questions on, and --non-interactive was not given.
  Either run it from a real shell:
      git clone https://github.com/dakshitha-a/NexusQC.git && cd NexusQC && scripts/install.sh
  or drive it unattended -- see --help for the environment it needs:
      scripts/install.sh --non-interactive --bind=localhost"
fi

# --- failure reporting --------------------------------------------------------
# One trap instead of a guard at every call site. Before this, a `read` that hit
# end of input, a certificate that failed to generate, or a Ctrl-C at the
# password prompt each ended the script under `set -e` with no output at all --
# the install simply stopped, part-way through, and said nothing about where.
QC_START_TS="$(date +%s)"
QC_STACK_STARTED=0

report_failure() {
    # $1 = exit status. Says where it stopped, which is the thing that was
    # missing: before this, a failed install simply ended, part-way through,
    # printing nothing at all.
    local rc="$1"
    # Defensive: `read -s` turns terminal echo off, and an interrupt taken at
    # exactly the wrong moment can leave it that way, which looks to the person
    # in the chair like their shell has broken.
    [ -t 0 ] && stty echo 2>/dev/null || true
    echo >&2
    if [ "$rc" -ge 128 ]; then
        echo "${YEL}install: cancelled during: ${QC_STEP_NAME}${RST}" >&2
    else
        echo "${RED}install: stopped unexpectedly during: ${QC_STEP_NAME} (exit ${rc})${RST}" >&2
    fi
    echo "  Nothing is half-written that a re-run cannot redo: this installer is" >&2
    echo "  safe to run again and will offer to keep the .env it already made." >&2
    if [ "$QC_STACK_STARTED" -eq 1 ] && [ "$rc" -lt 128 ]; then
        echo >&2
        echo "  The last few lines from the api container, in case they say why:" >&2
        "${QC_COMPOSE[@]}" logs --tail 15 api 2>&1 | sed 's/^/      /' >&2 || true
    fi
}

on_exit() {
    local rc=$?
    [ -t 0 ] && stty echo 2>/dev/null || true
    # die() has already explained itself, and a clean exit needs nothing.
    if [ "$rc" -eq 0 ] || [ "$QC_DIED" -eq 1 ]; then exit "$rc"; fi
    report_failure "$rc"
    exit "$rc"
}

# INT and TERM are trapped explicitly, not left to the EXIT trap. Bash does not
# reliably run an EXIT trap when it is killed by a signal it does not handle
# itself -- it re-raises and dies -- so a Ctrl-C during the build ended the
# install with no message at all, which is the exact failure this trap exists to
# prevent. Each handler clears the EXIT trap first so the report is printed
# once rather than twice.
on_signal() {
    local sig="$1"
    trap - EXIT INT TERM
    report_failure "$((128 + sig))"
    exit "$((128 + sig))"
}

trap on_exit EXIT
trap 'on_signal 2' INT
trap 'on_signal 15' TERM

echo "${BLD}NexusQC installer${RST}"
echo "Agentic Quantum Chemistry Engine -- first-time deployment setup."
[ "$QC_NONINTERACTIVE" -eq 1 ] && info "unattended run: --bind=${BIND_MODE}, pull-model=${WANT_PULL_MODEL}, updater=${WANT_UPDATER}"

# --- 1. can this host run it? -------------------------------------------------
step "checking your system"
require_tools git docker openssl curl
require_docker
ok "git, docker, docker compose, openssl and curl are all present and working"

# Both filesystems matter and they are usually different ones: the image is
# built and stored under docker's root, the checkout and all its data live
# here. Running out of either fails the install, in different ways.
#
# The 12 GB figure is measured, not guessed. A completed install occupies about
# 4.5 GB of images on this host: the api image is 3.39 GB without block2 and
# about 3.8 GB with it, on top of postgres:16-alpine at 420 MB,
# node:24-slim at 331 MB for the frontend build stage,
# python:3.11-slim-bookworm at 199 MB, nginx:1.27-alpine at 75 MB and
# redis:7-alpine at 58 MB. The rest of the allowance is the build itself, which
# holds intermediate layers -- npm's node_modules and pip's wheels among them --
# until it finishes. Refusing at 12 leaves room for that peak rather than for
# the steady state, because running out part-way through a twenty-minute build
# is the failure this exists to prevent.
DOCKER_ROOT="$(docker info --format '{{.DockerRootDir}}' 2>/dev/null || echo /var/lib/docker)"
require_disk "$DOCKER_ROOT" 12 "the images"
require_disk "$REPO_ROOT" 2 "the checkout and its data"
require_data_writable

# Whether this deployment is already running decides whether a bound 8443 is a
# conflict or just this stack. Re-running the installer to resume or reconfigure
# an existing deployment is a supported thing to do, and checking the port
# unconditionally made that die at the first step complaining about its own
# listener.
#
# Asked two ways, because the obvious one is not reliable here. `docker compose
# ps -q` has to parse docker-compose.yml, which needs variables out of .env --
# so on a reconfigure that has just removed .env, or any run where compose
# cannot resolve the file, it answers "nothing running" for a deployment that is
# very much running. The installer then refused to start, blaming "another
# service" for a port its own nginx was holding. The container labels carry the
# compose project name and need no config file at all, so they are asked first.
STACK_ALREADY_UP=0
QC_PROJECT="$(printf '%s' "$(basename "$REPO_ROOT")" | tr '[:upper:]' '[:lower:]' | tr -c 'a-z0-9_-' '-')"
if [ -n "$(docker ps -q --filter "label=com.docker.compose.project=${QC_PROJECT}" 2>/dev/null)" ]; then
    STACK_ALREADY_UP=1
elif [ -n "$(docker compose ps -q 2>/dev/null)" ]; then
    STACK_ALREADY_UP=1
fi
if [ "$STACK_ALREADY_UP" -eq 1 ]; then
    info "this deployment is already running; leaving its published ports alone"
else
    require_port_free "127.0.0.1:8443"
fi

info "Node is not needed on this host: the frontend bundle is built inside the"
info "api image and copied out by scripts/extract_frontend.sh."

# --- 2. install location ------------------------------------------------------
step "install location"
echo "  Installing into: ${BLD}${REPO_ROOT}${RST}"
echo "  Everything this deployment ever writes -- job results, the knowledge"
echo "  base, uploaded files, the molecule cache -- lives under ${REPO_ROOT}/data."
echo "  There is no separate data-directory setting: wherever this clone sits is"
echo "  where it lives. To move it later, stop the stack and move the whole clone."
if [ "$QC_NONINTERACTIVE" -eq 0 ]; then
    ask_yn "Continue installing here?" y
    [ "$ASK_YN_OK" -eq 1 ] || die "stopped -- clone NexusQC where you want it and re-run there."
fi

# --- 3. configuration ---------------------------------------------------------
step "configuration"
REGEN=1
if [ -f .env ]; then
    warn "this checkout is already configured (.env exists)."
    if [ "$QC_NONINTERACTIVE" -eq 1 ]; then
        ASK_YN_OK=0
        info "keeping it -- an unattended run never regenerates secrets."
    else
        echo "  Starting over generates new secrets, which every existing session"
        echo "  and login will be invalidated by. Keeping it goes straight to"
        echo "  building and starting, which is what you want to resume an install."
        ask_yn "Reconfigure from scratch? (a timestamped backup is kept)" n
    fi
    if [ "$ASK_YN_OK" -eq 1 ]; then
        ENV_BACKUP=".env.bak.$(date +%Y%m%d-%H%M%S)"
        cp .env "$ENV_BACKUP"
        chmod 600 "$ENV_BACKUP"
        ok "existing .env backed up to ${ENV_BACKUP}"
    else
        REGEN=0
        ok "keeping the existing configuration"
        # The remaining steps are build, start, admin and the updater question:
        # renumber so the counter does not appear to skip.
        QC_STEP_TOTAL=$(( QC_STEP_INDEX + 4 ))
        # A --bind that will not be honoured is worth saying out loud. Silently
        # ignoring it means someone who asked for the tailnet does not find out
        # until they try to reach the deployment from a laptop.
        if [ -n "$BIND_MODE" ]; then
            warn "--bind=${BIND_MODE} is being ignored: the network exposure is already"
            warn "set in .env and docker-compose.override.yml. Reconfigure to change it."
        fi
    fi
fi

if [ "$REGEN" -eq 1 ]; then
    [ -f .env.example ] || die "no .env.example in this checkout -- is this a real NexusQC clone?"
    cp .env.example .env
    chmod 600 .env

    PG_PASSWORD="$(openssl rand -hex 24)"
    JWT_SECRET="$(openssl rand -hex 32)"
    DEPLOY_SECRET="$(openssl rand -hex 32)"
    envset QC_AGENT_POSTGRES_PASSWORD "$PG_PASSWORD"
    envset QC_AGENT_JWT_SECRET "$JWT_SECRET"
    envset QC_AGENT_DEPLOY_SECRET "$DEPLOY_SECRET"
    ok "generated a Postgres password, a JWT signing secret and a deploy-request secret"

    APP_UID="$(id -u)"; APP_GID="$(id -g)"
    envset APP_UID "$APP_UID"
    envset APP_GID "$APP_GID"
    ok "the container will run as ${APP_UID}:${APP_GID}, so files under data/ stay yours"

    # --- 4. network exposure and certificate ---------------------------------
    step "where this should be reachable"

    TS_IP=""; LAN_IP=""
    DETECTED_TS=""
    if command -v tailscale >/dev/null 2>&1; then
        DETECTED_TS="$(tailscale ip -4 2>/dev/null | head -n1 || true)"
    fi
    DETECTED_LAN="$(ip route get 1.1.1.1 2>/dev/null | sed -nE 's/.*src ([0-9.]+).*/\1/p' | head -n1)"

    if [ -n "$BIND_MODE" ]; then
        # A mode naming an address this host does not have is a refusal rather
        # than a silent downgrade to localhost: someone who typed
        # --bind=tailscale wants the tailnet, and quietly not publishing there
        # is the kind of thing nobody notices until they cannot reach the
        # deployment from a laptop.
        case "$BIND_MODE" in
            lan|both)
                [ -n "$DETECTED_LAN" ] || die "--bind=${BIND_MODE} asks for this host's LAN address, but none could
  be detected (\`ip route get 1.1.1.1\` found no source address). Run without
  --bind to enter one by hand."
                LAN_IP="$DETECTED_LAN" ;;
        esac
        case "$BIND_MODE" in
            tailscale|both)
                [ -n "$DETECTED_TS" ] || die "--bind=${BIND_MODE} asks for the tailnet address, but Tailscale is not
  installed or is not up on this host. Install and start it, or use
  --bind=localhost or --bind=lan."
                TS_IP="$DETECTED_TS" ;;
        esac
        ok "publishing per --bind=${BIND_MODE}"
    else
        # One question, not the three this used to ask. The options are built
        # from what this host actually has, so nothing is offered that cannot
        # work and nothing available is hidden.
        echo "  127.0.0.1 is always reachable and cannot be turned off. Anything"
        echo "  else is opt-in. This deployment has no public-internet listener;"
        echo "  serving one is a deliberate step, described in docs/DEPLOYMENT.md."
        echo
        echo "    ${BLD}1${RST}) this machine only"
        _n=1
        _opt_lan=""; _opt_ts=""; _opt_both=""; _opt_manual=""
        if [ -n "$DETECTED_LAN" ]; then
            _n=$((_n+1)); _opt_lan="$_n"
            echo "    ${BLD}${_n}${RST}) also this host's LAN address, ${DETECTED_LAN}"
        fi
        if [ -n "$DETECTED_TS" ]; then
            _n=$((_n+1)); _opt_ts="$_n"
            echo "    ${BLD}${_n}${RST}) also this host's tailnet address, ${DETECTED_TS}"
        fi
        if [ -n "$DETECTED_LAN" ] && [ -n "$DETECTED_TS" ]; then
            _n=$((_n+1)); _opt_both="$_n"
            echo "    ${BLD}${_n}${RST}) both of those"
        fi
        _n=$((_n+1)); _opt_manual="$_n"
        echo "    ${BLD}${_n}${RST}) another address I will type"
        echo
        while :; do
            ask "  Choose 1-${_n} " "1"
            case "$REPLY" in
                1) break ;;
                "$_opt_lan")  [ -n "$_opt_lan" ]  && { LAN_IP="$DETECTED_LAN"; break; } ;;
                "$_opt_ts")   [ -n "$_opt_ts" ]   && { TS_IP="$DETECTED_TS"; break; } ;;
                "$_opt_both") [ -n "$_opt_both" ] && { LAN_IP="$DETECTED_LAN"; TS_IP="$DETECTED_TS"; break; } ;;
                "$_opt_manual")
                    while :; do
                        ask "  IP address to publish on: "
                        if valid_ipv4 "$REPLY"; then LAN_IP="$REPLY"; break; fi
                        # Caught here rather than by openssl. This value becomes
                        # `IP:<value>` in the certificate's subjectAltName, and a
                        # hostname there used to end the whole install with no
                        # message at all.
                        warn "that is not an IPv4 address. A hostname will not work here:"
                        warn "the certificate needs a literal address, e.g. 192.168.1.50."
                    done
                    break ;;
            esac
            warn "please choose a number between 1 and ${_n}."
        done
    fi

    if [ -n "$LAN_IP" ]; then
        [ "$STACK_ALREADY_UP" -eq 1 ] || require_port_free "${LAN_IP}:8443"
        ok "publishing on ${LAN_IP}"
    fi
    if [ -n "$TS_IP" ]; then
        [ "$STACK_ALREADY_UP" -eq 1 ] || require_port_free "${TS_IP}:8443"
        ok "publishing on ${TS_IP} (tailnet)"
    fi
    [ -z "$LAN_IP" ] && [ -z "$TS_IP" ] && info "localhost only -- nothing else will be published"

    # Cert vars need real (or harmless placeholder) values regardless of what
    # gets published -- gen_intranet_cert.sh requires all three, and an unused
    # one just becomes an extra, harmless SAN entry.
    CERT_FQDN="$(hostname -f 2>/dev/null || hostname)"
    if [ "$QC_NONINTERACTIVE" -eq 0 ]; then
        echo
        echo "  The certificate names this host as ${BLD}${CERT_FQDN}${RST}. That has to match"
        echo "  what people actually type in the browser, or it will not verify."
        ask "  Press enter to accept, or type the name to use: " "$CERT_FQDN"
        CERT_FQDN="$REPLY"
    fi
    envset QC_AGENT_CERT_FQDN "$CERT_FQDN"
    envset QC_AGENT_LAN_BIND "${LAN_IP:-127.0.0.1}"
    envset QC_AGENT_TAILSCALE_BIND "${TS_IP:-127.0.0.1}"

    # Guarded, unlike before. gen_intranet_cert.sh exits non-zero on a bad SAN,
    # and an unguarded call under `set -e` simply ended the install in silence.
    set -a; source .env; set +a
    QC_CERT_DRIVEN=1 bash scripts/gen_intranet_cert.sh \
        || die "could not generate the TLS certificate -- see the openssl error above."
    _covers="${CERT_FQDN}, localhost, 127.0.0.1"
    [ -n "$LAN_IP" ] && _covers="${_covers}, ${LAN_IP}"
    [ -n "$TS_IP" ] && _covers="${_covers}, ${TS_IP}"
    ok "certificate covers ${_covers}"
    warn "it is self-signed, so browsers warn once per client machine until it is trusted."

    # Ports override. docker-compose.yml's own ports list still needs
    # QC_AGENT_LAN_BIND/QC_AGENT_TAILSCALE_BIND to hold SOME value for compose
    # to parse the file at all, which is why they are set above even when
    # unused -- but this override is what actually controls exposure.
    PORTS_YAML="      - \"127.0.0.1:8443:8443\""
    [ -n "$LAN_IP" ] && PORTS_YAML="${PORTS_YAML}
      - \"${LAN_IP}:8443:8443\""
    [ -n "$TS_IP" ] && PORTS_YAML="${PORTS_YAML}
      - \"${TS_IP}:8443:8443\""

    # --- 5. engines -----------------------------------------------------------
    step "calculation engines"
    echo "  PySCF is bundled and needs nothing here. On its own it covers"
    echo "  single-point energies, geometry optimisation, frequencies, excited"
    echo "  states, coupled cluster, CASSCF and orbital visualisation."

    find_first() { for p in "$@"; do [ -e "$p" ] && { echo "$p"; return 0; }; done; return 1; }

    # `readlink -f` before anything else. The bind mount written below is
    # derived from the binary's directory, so a symlink at /usr/local/bin/orca
    # pointing into /opt/orca6 would mount /usr/local/bin and leave orca_scf,
    # orca_gtoint and the rest of the suite outside the container -- an install
    # that reports success and a first job that fails.
    resolve_bin() { readlink -f "$1" 2>/dev/null || echo "$1"; }

    ask_engine() {
        # $1 = display name, $2 = what it adds, $3.. = candidate paths.
        # Sets ENGINE_BIN.
        local name="$1" adds="$2"; shift 2
        local candidate=""
        ENGINE_BIN=""
        candidate="$(find_first "$@" 2>/dev/null || true)"
        [ -z "$candidate" ] && command -v "$name" >/dev/null 2>&1 && candidate="$(command -v "$name")"
        if [ -n "$candidate" ]; then
            candidate="$(resolve_bin "$candidate")"
            if [ "$QC_NONINTERACTIVE" -eq 1 ]; then
                ENGINE_BIN="$candidate"; ok "using ${name} at ${candidate}"; return 0
            fi
            ask_yn "  Found ${name} at ${candidate} -- use it?" y
            [ "$ASK_YN_OK" -eq 1 ] && { ENGINE_BIN="$candidate"; return 0; }
        fi
        [ "$QC_NONINTERACTIVE" -eq 1 ] && return 0
        ask_yn "  Enter a ${name} path manually? (${adds})" n
        if [ "$ASK_YN_OK" -eq 1 ]; then
            ask "  Path to the ${name} binary: "
            if [ -x "$REPLY" ]; then
                ENGINE_BIN="$(resolve_bin "$REPLY")"
            else
                warn "not an executable file -- skipping ${name}."
            fi
        fi
    }

    # Looked for in more places than /opt. An institutional install commonly
    # lives under /usr/local or a shared software tree, and someone who has to
    # answer "no" and then type the path they were just not asked about has
    # been made to do the installer's work.
    ask_engine orca "adds oscillator strengths for CASSCF/EOM-CCSD, and NEB-TS" \
        /opt/orca*/orca /usr/local/orca*/orca /usr/local/bin/orca "$HOME"/orca*/orca
    ORCA_BIN="$ENGINE_BIN"
    [ -z "$ORCA_BIN" ] && [ "$QC_NONINTERACTIVE" -eq 0 ] \
        && info "skipping ORCA -- it is free for academic use from https://orcaforum.kofo.mpg.de/;" \
        && info "  re-run this installer once it is installed."

    ask_engine BAGEL "adds CASPT2" \
        /opt/bagel*/bin/BAGEL /usr/local/bagel*/bin/BAGEL "$HOME"/bagel*/bin/BAGEL
    BAGEL_BIN="$ENGINE_BIN"
    [ -z "$BAGEL_BIN" ] && [ "$QC_NONINTERACTIVE" -eq 0 ] \
        && info "skipping BAGEL -- source is at https://nubakery.org/ if you want it later."

    BAGEL_SETVARS=""
    if [ -n "$BAGEL_BIN" ]; then
        CANDIDATE="$(find_first /opt/intel/oneapi/setvars.sh 2>/dev/null || true)"
        if [ -n "$CANDIDATE" ]; then
            BAGEL_SETVARS="$CANDIDATE"
            ok "found Intel oneAPI setvars.sh at ${BAGEL_SETVARS}"
        elif [ "$QC_NONINTERACTIVE" -eq 0 ]; then
            ask_yn "  BAGEL needs Intel oneAPI's setvars.sh for MKL/TBB -- enter its path?" n
            if [ "$ASK_YN_OK" -eq 1 ]; then
                ask "  Path to setvars.sh: "
                if [ -f "$REPLY" ]; then
                    BAGEL_SETVARS="$REPLY"
                else
                    warn "file not found -- BAGEL may fail to launch without it."
                fi
            fi
        fi
    fi

    if [ -z "$ORCA_BIN" ] && [ -z "$BAGEL_BIN" ]; then
        info "no ORCA or BAGEL configured -- this deployment will run PySCF jobs only,"
        info "  which is a complete deployment, not a degraded one."
    fi

    # block2 is unlike ORCA and BAGEL: an ordinary pip package with no licence
    # to chase, optional purely on size. Asked rather than installed by default
    # because it is 379 MB with its own bundled MKL, and the exact-FCI pilot it
    # competes with covers every screening pool up to 12 orbitals. Declining is
    # not a degraded install: the app detects the absence and stops offering the
    # option instead of failing on it.
    INSTALL_DMRG=0
    if [ "$QC_NONINTERACTIVE" -eq 0 ]; then
        echo
        echo "  The active-space recommender can screen larger orbital pools with"
        echo "  block2, a DMRG backend. It adds about 379 MB to the image and"
        echo "  raises the screening ceiling from 12 orbitals to 30."
        ask_yn "  Install it?" n
        [ "$ASK_YN_OK" -eq 1 ] && INSTALL_DMRG=1
    fi
    if [ "$INSTALL_DMRG" -eq 1 ]; then
        ok "block2 will be built into the image"
    else
        info "skipping block2 -- the entropy pilot will use exact FCI only."
        info "  To add it later: set QC_AGENT_INSTALL_DMRG=1 in .env and rebuild."
    fi
    envset QC_AGENT_INSTALL_DMRG "$INSTALL_DMRG"

    # --- 6. the language model ------------------------------------------------
    step "language model"
    LLM_MODEL="$(envget .env QC_AGENT_LLM_MODEL)"
    LLM_MODEL="${LLM_MODEL:-qwen3.8:27b}"
    # Derived, not hardcoded. .env points the *container* at Ollama, commonly as
    # host.docker.internal, which resolves only inside a container -- so the
    # host-side probe has to translate it. A deployment pointed at another
    # machine's Ollama was previously told its model was unreachable when it was
    # perfectly fine.
    LLM_URL="$(envget .env QC_AGENT_LLM_BASE_URL)"
    LLM_URL="${LLM_URL:-http://host.docker.internal:11434/v1}"
    LLM_PROBE="${LLM_URL%/v1}"
    LLM_PROBE="${LLM_PROBE/host.docker.internal/127.0.0.1}"
    OLLAMA_TAGS="$(mktemp)"
    if curl -fsS --max-time 5 "${LLM_PROBE}/api/tags" -o "$OLLAMA_TAGS" 2>/dev/null; then
        if grep -qF "\"${LLM_MODEL}\"" "$OLLAMA_TAGS" 2>/dev/null; then
            ok "reachable at ${LLM_PROBE}, and ${LLM_MODEL} is already pulled"
        else
            warn "reachable at ${LLM_PROBE}, but ${LLM_MODEL} is not pulled yet."
            if [ "$WANT_PULL_MODEL" = "ask" ]; then
                echo "  It is a large download, typically tens of gigabytes, and chat will"
                echo "  not work until it is present. You can also pull it later."
                ask_yn "  Pull it now?" y
                [ "$ASK_YN_OK" -eq 1 ] && WANT_PULL_MODEL=yes || WANT_PULL_MODEL=no
            fi
            if [ "$WANT_PULL_MODEL" = "yes" ]; then
                if command -v ollama >/dev/null 2>&1; then
                    ollama pull "$LLM_MODEL" || warn "pull failed -- chat will not work until a model is available."
                else
                    warn "the ollama CLI is not on PATH here -- pull it on the Ollama host:"
                    warn "    ollama pull ${LLM_MODEL}"
                fi
            else
                info "skipped -- pull it later with: ollama pull ${LLM_MODEL}"
            fi
        fi
    else
        # A warning, never a failure. Ollama is not part of this stack, and an
        # otherwise-good deployment should finish installing and tell you what
        # is missing rather than refuse.
        warn "no language model server answering at ${LLM_PROBE}."
        warn "Everything else will install; chat will not work until one is running."
        warn "Install it from https://ollama.com/download, then: ollama pull ${LLM_MODEL}"
    fi
    rm -f "$OLLAMA_TAGS"

    if [ ! -d data/scraped ] || [ -z "$(ls -A data/scraped 2>/dev/null)" ]; then
        info "the RAG knowledge base will start EMPTY, not degraded. Seed it whenever"
        info "  you like with: python3 scripts/seed_knowledge_base.py"
    fi

    # --- write docker-compose.override.yml ------------------------------------
    # Not written blind. This file is gitignored, so a hand-edited one -- engine
    # mounts, a remapped port, anything site-specific -- cannot be recovered
    # once it is gone. The header this writes has always claimed the installer
    # asks first; now it does.
    OVERRIDE_NEW="$(mktemp)"
    {
        echo "# Generated by scripts/install.sh on $(date -Is)."
        echo "# Safe to hand-edit afterwards: re-running the installer shows you a diff"
        echo "# and asks before replacing it."
        echo "services:"
        echo "  nginx:"
        echo "    ports: !override"
        echo "$PORTS_YAML"
        if [ -n "$ORCA_BIN" ] || [ -n "$BAGEL_BIN" ]; then
            echo "  api:"
            echo "    environment:"
            [ -n "$ORCA_BIN" ] && echo "      QC_AGENT_ORCA_BIN: ${ORCA_BIN}"
            [ -n "$BAGEL_BIN" ] && echo "      QC_AGENT_BAGEL_BIN: ${BAGEL_BIN}"
            [ -n "$BAGEL_SETVARS" ] && echo "      QC_AGENT_BAGEL_SETVARS: ${BAGEL_SETVARS}"
            echo "    volumes:"
            [ -n "$ORCA_BIN" ] && echo "      - $(dirname "$ORCA_BIN"):$(dirname "$ORCA_BIN"):ro"
            [ -n "$BAGEL_BIN" ] && echo "      - $(dirname "$(dirname "$BAGEL_BIN")"):$(dirname "$(dirname "$BAGEL_BIN")"):ro"
            [ -n "$BAGEL_SETVARS" ] && echo "      - $(dirname "$BAGEL_SETVARS"):$(dirname "$BAGEL_SETVARS"):ro"
        fi
    } > "$OVERRIDE_NEW"

    # The comparison ignores the "Generated on <timestamp>" line, or the file
    # would differ from itself on every single re-run and this would ask about
    # nothing but a changed date -- which is exactly how people learn to answer
    # yes to a confirmation without reading it.
    override_body() { grep -v '^# Generated by scripts/install.sh on ' "$1"; }

    WRITE_OVERRIDE=1
    if [ -f docker-compose.override.yml ] && [ "$FORCE_OVERRIDE" -eq 0 ]; then
        if diff -q <(override_body docker-compose.override.yml) \
                   <(override_body "$OVERRIDE_NEW") >/dev/null 2>&1; then
            # Identical but for the timestamp: leave the file alone, so its
            # date keeps saying when the content was last actually written.
            WRITE_OVERRIDE=0
        elif [ "$QC_NONINTERACTIVE" -eq 1 ]; then
            WRITE_OVERRIDE=0
            warn "docker-compose.override.yml differs from what this run would write, and"
            warn "an unattended run will not replace it. Use --force-override to overwrite."
        else
            warn "docker-compose.override.yml already exists and differs from what this"
            warn "run would write. It is not tracked by git, so replacing it is final."
            echo
            diff -u --label "on disk now" --label "what this run would write" \
                 <(override_body docker-compose.override.yml) \
                 <(override_body "$OVERRIDE_NEW") \
                | sed -e "s/^-/${RED}-/" -e "s/^+/${GRN}+/" -e "s/$/${RST}/" \
                | sed 's/^/    /' || true
            echo
            ask_yn "  Replace it?" n
            [ "$ASK_YN_OK" -eq 1 ] || WRITE_OVERRIDE=0
        fi
    fi
    if [ "$WRITE_OVERRIDE" -eq 1 ]; then
        cp "$OVERRIDE_NEW" docker-compose.override.yml
        # Explicit, because it is staged through mktemp, which creates at 0600.
        # Inheriting that would silently make the file more restrictive than the
        # 0644 a plain redirect used to give it, and quietly changing the
        # permissions of someone's config as a side effect of a refactor is not
        # a thing to leave to chance. There are no secrets in it -- engine paths
        # and port bindings -- unlike .env, which stays 0600 deliberately.
        chmod 644 docker-compose.override.yml
        ok "wrote docker-compose.override.yml"
    else
        ok "kept the existing docker-compose.override.yml"
    fi
    rm -f "$OVERRIDE_NEW"
fi

set -a; source .env; set +a

# --- 7. build -----------------------------------------------------------------
step "building the images"
echo "  This is the long part: ten to twenty minutes on a first install, and it"
echo "  happens once. Docker prints its own progress below. Subsequent updates"
echo "  reuse most of these layers and take a fraction of the time."
echo
# Stamped here, not only in update.sh. Without it a fresh install carries
# GIT_COMMIT=unknown, which deployed_commit() reads as "cannot tell, assume
# stale" -- so the first update after an install always rebuilt everything for
# no reason, and the deployment could never say what it was running.
QC_AGENT_BUILD_COMMIT="$(git rev-parse HEAD 2>/dev/null || echo unknown)"
export QC_AGENT_BUILD_COMMIT
BUILD_START="$(date +%s)"
docker compose build || die "the image build failed -- the error is in the output above.
  Nothing has been started, and re-running this installer picks up from here."
ok "images built at ${QC_AGENT_BUILD_COMMIT:0:12} in $(qc_elapsed_human $(( $(date +%s) - BUILD_START )))"

info "installing the frontend bundle from the image"
bash scripts/extract_frontend.sh "$QC_AGENT_BUILD_COMMIT" \
    || die "could not install the frontend bundle -- see the output above."

# --- 8. start -----------------------------------------------------------------
step "starting the stack"
docker compose up -d || die "docker compose up failed -- see the output above."
QC_STACK_STARTED=1

HEALTH_URLS="$(health_urls)"
info "waiting for the api to come up. The first start imports the agent graph and"
info "creates the database schema, so up to a couple of minutes is normal."
qc_wait_for_health 300 "$HEALTH_URLS"; HEALTH_RC=$?
STACK_HEALTHY=0
case "$HEALTH_RC" in
    0) STACK_HEALTHY=1; ok "healthy at ${QC_HEALTH_URL}" ;;
    2) warn "a container stopped while starting: ${QC_STOPPED_SERVICES}"
       warn "Its last lines:"
       # Deliberately unquoted: more than one service may have stopped, and
       # each is a separate argument. The names come from compose, not input.
       # shellcheck disable=SC2086
       docker compose logs --tail 25 ${QC_STOPPED_SERVICES} 2>&1 | sed 's/^/      /' || true ;;
    *) warn "the stack did not answer within 300s."
       warn "The api healthcheck allows a 90s start_period, so a slow first import"
       warn "is not automatically a failure -- it may still be coming up."
       warn "The last lines from the api container:"
       docker compose logs --tail 25 api 2>&1 | sed 's/^/      /' || true ;;
esac

# Proving the engine mount rather than assuming it. The override binds the
# binary's directory into the container; a wrong path, a symlink resolved
# incorrectly or a missing mount all produce an install that reports success
# and a first calculation that fails with a confusing error days later.
if [ "$STACK_HEALTHY" -eq 1 ]; then
    # Asked of compose, not of the environment. Engine paths are written into
    # docker-compose.override.yml and never into .env, so reading them from the
    # shell found nothing and this check quietly did not happen -- which is the
    # exact failure mode it exists to catch, one level up.
    _cfg="$(docker compose config 2>/dev/null || true)"
    _orca="$(printf '%s\n' "$_cfg" | sed -nE 's/^[[:space:]]*QC_AGENT_ORCA_BIN:[[:space:]]*(.+)$/\1/p' | head -n1)"
    _bagel="$(printf '%s\n' "$_cfg" | sed -nE 's/^[[:space:]]*QC_AGENT_BAGEL_BIN:[[:space:]]*(.+)$/\1/p' | head -n1)"
    for _pair in "ORCA:${_orca}" "BAGEL:${_bagel}"; do
        _name="${_pair%%:*}"; _path="${_pair#*:}"
        [ -n "$_path" ] || continue
        if docker compose exec -T api test -x "$_path" </dev/null 2>/dev/null; then
            ok "${_name} is reachable inside the container at ${_path}"
        else
            warn "${_name} is configured as ${_path} but is not executable inside the"
            warn "container. Check the bind mount in docker-compose.override.yml."
        fi
    done
fi

# --- 9. first admin -----------------------------------------------------------
if [ "$STACK_HEALTHY" -eq 0 ]; then
    step "your admin account"
    warn "skipped: the stack is built and started but not answering yet, and"
    warn "creating an account needs a working database."
    warn "Once it is healthy, re-run this installer -- it will keep this"
    warn "configuration and pick up from here."
    QC_DIED=1
    echo
    echo "${YEL}install: incomplete.${RST} Everything is built and started; only the admin"
    echo "  account is missing."
    echo
    echo "  It should come up at:"
    for _u in $HEALTH_URLS; do echo "    ${_u}"; done
    echo
    echo "  Look at ${BLD}docker compose logs api${RST}, then re-run to finish:"
    echo "      cd ${REPO_ROOT} && scripts/install.sh"
    exit 1
fi

# `< /dev/null` matters here, not just for tidiness: `docker compose exec -T`
# relays this script's own stdin to the container and drains it fully before
# returning, even though `psql -c` needs no input at all -- without this
# redirect it silently swallows the admin-account answers still waiting on
# stdin below, and the next `read` hits EOF and kills the script with no error
# message right at the "Email:" prompt.
ADMIN_EXISTS="$(docker compose exec -T postgres psql -At -U "${QC_AGENT_POSTGRES_USER:-qc_agent}" -d "${QC_AGENT_POSTGRES_DB:-qc_agent}" -c "SELECT count(*) FROM users WHERE role='admin'" < /dev/null 2>/dev/null || echo "0")"
if [ "${ADMIN_EXISTS:-0}" -gt 0 ] 2>/dev/null; then
    step "your admin account"
    ok "an admin account already exists -- leaving it alone"
else
    step "your admin account"
    echo "  This is the account you will sign in with, and the one that invites"
    echo "  everyone else. It can be changed later from the admin panel."
    echo
    if [ "$QC_NONINTERACTIVE" -eq 1 ]; then
        ADMIN_EMAIL="$NEXUSQC_ADMIN_EMAIL"
        ADMIN_USERNAME="$NEXUSQC_ADMIN_USERNAME"
        ADMIN_FIRST="$NEXUSQC_ADMIN_FIRSTNAME"
        ADMIN_LAST="$NEXUSQC_ADMIN_LASTNAME"
        ADMIN_PASS="$NEXUSQC_ADMIN_PASSWORD"
        info "taking the admin details from the environment"
    else
        # Asked in a loop rather than accepted blank. An empty username reaches
        # bootstrap-admin as an empty string, and what happens then is the
        # admin CLI's business rather than something to find out here.
        while :; do
            ask "  Email: "; ADMIN_EMAIL="$REPLY"
            case "$ADMIN_EMAIL" in
                ?*@?*.?*) break ;;
                *) warn "that does not look like an email address." ;;
            esac
        done
        while :; do
            ask "  Username: "; ADMIN_USERNAME="$REPLY"
            [ -n "$ADMIN_USERNAME" ] && break
            warn "a username is required."
        done
        while :; do
            ask "  First name: "; ADMIN_FIRST="$REPLY"
            [ -n "$ADMIN_FIRST" ] && break
            warn "a first name is required."
        done
        while :; do
            ask "  Last name: "; ADMIN_LAST="$REPLY"
            [ -n "$ADMIN_LAST" ] && break
            warn "a last name is required."
        done
        while :; do
            printf '  Password (at least 8 characters): ' >&2
            read -r -s ADMIN_PASS || die "no more input while asking for the password."
            echo >&2
            printf '  Confirm password: ' >&2
            read -r -s ADMIN_PASS2 || die "no more input while confirming the password."
            echo >&2
            [ "$ADMIN_PASS" = "$ADMIN_PASS2" ] || { warn "those did not match -- try again."; continue; }
            [ "${#ADMIN_PASS}" -ge 8 ] || { warn "at least 8 characters, please."; continue; }
            break
        done
    fi
    printf '%s\n' "$ADMIN_PASS" | docker compose exec -T api python -m server.admin_cli bootstrap-admin \
        --email "$ADMIN_EMAIL" --username "$ADMIN_USERNAME" \
        --first-name "$ADMIN_FIRST" --last-name "$ADMIN_LAST" --password-stdin \
        || die "creating the admin account failed -- see the output above.
  Everything else is installed; re-run this installer to try again."
    ok "admin account created: ${ADMIN_USERNAME} <${ADMIN_EMAIL}>"
fi

# --- 10. the in-app update path -----------------------------------------------
# Opt-in, and asked rather than assumed: it installs a systemd --user unit,
# which is a change to this host outside the checkout, and the admin panel is
# useful without it (it still reports what is deployed and what an update would
# break -- it just shows the host command instead of an Apply button).
step "updating from inside the app (optional)"
if [ "$WANT_UPDATER" = "ask" ]; then
    echo "  The admin panel can run updates itself. That needs a small systemd user"
    echo "  service on this host to do the part the container cannot: git, docker"
    echo "  compose and the restart. Without it the panel still shows what is"
    echo "  deployed and who an update would interrupt, and names scripts/update.sh."
    ask_yn "  Install it?" y
    [ "$ASK_YN_OK" -eq 1 ] && WANT_UPDATER=yes || WANT_UPDATER=no
fi
if [ "$WANT_UPDATER" = "yes" ]; then
    bash scripts/install_updater.sh \
        || warn "the updater service could not be installed; the panel will fall back to showing the host command."
else
    info "skipped -- install it later with: scripts/install_updater.sh"
fi

# --- done ---------------------------------------------------------------------
# Rebuilt from what is actually configured, not from variables that exist on
# only one branch. Choosing "keep the existing .env" used to reach this point
# with LAN_IP, TS_IP, ORCA_BIN and BAGEL_BIN all unset, and so reported a
# tailnet-published deployment with both engines as localhost-only and PySCF.
banner "done"
COMPOSE_CONFIG="$(docker compose config 2>/dev/null || true)"
echo "  ${GRN}${BLD}NexusQC is up.${RST}  (installed in $(qc_elapsed_human $(( $(date +%s) - QC_START_TS ))))"
echo
echo "  ${BLD}Open it at:${RST}"
for _u in $(health_urls); do
    case "$_u" in
        *127.0.0.1*) echo "    ${_u}    (this machine)" ;;
        *)           echo "    ${_u}" ;;
    esac
done
echo
echo "  Sign in as the admin account above. Everyone else joins by invite,"
echo "  from the admin panel under Users."
echo
echo "  ${BLD}Worth knowing:${RST}"
echo "    - The certificate is self-signed, so each browser warns once. Accept it,"
echo "      or install a real certificate over nginx/certs/intranet.{crt,key}."
_engines=""
printf '%s' "$COMPOSE_CONFIG" | grep -q 'QC_AGENT_ORCA_BIN' && _engines="${_engines}ORCA "
printf '%s' "$COMPOSE_CONFIG" | grep -q 'QC_AGENT_BAGEL_BIN' && _engines="${_engines}BAGEL "
if [ -n "$_engines" ]; then
    echo "    - Engines available: PySCF ${_engines% }"
else
    echo "    - Engines available: PySCF only. Re-run this installer after installing"
    echo "      ORCA or BAGEL to add them."
fi
if [ ! -d data/scraped ] || [ -z "$(ls -A data/scraped 2>/dev/null)" ]; then
    echo "    - The knowledge base is empty. Seed it when you like:"
    echo "        python3 scripts/seed_knowledge_base.py"
fi
echo "    - Data lives in ${REPO_ROOT}/data"
echo
echo "  ${BLD}Later:${RST}"
echo "    scripts/backup.sh --full      back this deployment up"
echo "    scripts/update.sh             move it to a newer version"
echo "    docs/DEPLOYMENT.md            everything above, by hand"

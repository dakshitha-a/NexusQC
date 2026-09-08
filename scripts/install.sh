#!/usr/bin/env bash
# Interactive first-time setup for a NexusQC deployment: generates secrets,
# picks a network exposure, detects (or asks for) ORCA/BAGEL, checks Ollama,
# builds the stack and creates the first admin account.
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
# of them. Getting this wrong is not subtle-but-survivable: it kills the
# one-liner on every Debian-family machine, which is most of them.
#
# Wherever this checkout ends up is where data/ (jobs, KB, uploads, the
# molecule cache) will live, as a bind mount under docker-compose.yml -- there
# is no separate "data directory" setting, only where you put the clone.
#
# WHAT THIS DOES, IN ORDER
#   1. checks for git, docker, openssl, curl
#   2. confirms the install location and what lives there
#   3. writes .env with fresh secrets and this host's uid/gid
#   4. asks how the stack should be reachable (localhost is always on;
#      LAN and/or Tailscale are opt-in) and generates a matching TLS cert
#   5. detects ORCA/BAGEL, or asks for their paths, or lets you skip either
#   5b. offers the optional DMRG backend (block2), off by default
#   6. checks that Ollama is reachable and the configured model is present
#   7. builds the stack and takes frontend/dist out of the built image
#   8. starts everything and waits for it to become healthy
#   9. creates the first admin account
#  10. prints the reachable URL(s) and what to do next
#
# Usage:
#     scripts/install.sh [--dir=PATH] [--repo=URL] [--bind=MODE] [--help]
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
usage: install.sh [--dir=PATH] [--repo=URL] [--bind=MODE]

  --dir     where to clone NexusQC when run from a pipe, default
            ~/apps/NexusQC. Ignored when run from inside a checkout.
            Also settable as NEXUSQC_DIR.
  --repo    which repository to clone, for a fork or a local path.
            Also settable as NEXUSQC_REPO.
  --bind    pre-answer the network question, skipping its prompts:
              localhost   this machine only (always on regardless)
              lan         also this host's LAN address
              tailscale   also this host's tailnet address
              both        LAN and tailnet

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

RED=$'\033[31m'; GRN=$'\033[32m'; YEL=$'\033[33m'; DIM=$'\033[2m'; BLD=$'\033[1m'; RST=$'\033[0m'

SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SELF_DIR/.." && pwd)"
cd "$REPO_ROOT"

die()  { echo "${RED}install: $*${RST}" >&2; exit 1; }
ok()   { echo "${GRN}  ok${RST}  $*"; }
info() { echo "${DIM}  ..${RST}  $*"; }
warn() { echo "${YEL}  !!${RST}  $*"; }
step() { echo; echo "${BLD}--- $* ---------------------------------------${RST}"; }
ask()  { printf '%s' "$1" >&2; read -r REPLY; }
ask_yn() {
    # $1 = prompt, $2 = default (y/n). Sets ASK_YN_OK to 0/1.
    local def="${2:-n}" prompt_suffix="[y/N]"
    [ "$def" = "y" ] && prompt_suffix="[Y/n]"
    printf '%s %s ' "$1" "$prompt_suffix" >&2
    read -r reply
    reply="${reply:-$def}"
    case "$reply" in [yY]*) ASK_YN_OK=1 ;; *) ASK_YN_OK=0 ;; esac
}

envset() {
    # Idempotently sets KEY=VALUE in .env, appending if the key is absent.
    # Replaces an active line if one exists; otherwise an env.example-style
    # commented-out placeholder for the same key (`# KEY=...`), so a value
    # this installer fills in doesn't leave both the commented example and
    # the real value sitting in the file; otherwise appends a new line.
    local key="$1" value="$2" escaped
    escaped="${value//#/\\#}"
    if grep -qE "^${key}=" .env 2>/dev/null; then
        sed -i -E "s#^${key}=.*#${key}=${escaped}#" .env
    elif grep -qE "^#[[:space:]]*${key}=" .env 2>/dev/null; then
        sed -i -E "s|^#[[:space:]]*${key}=.*|${key}=${escaped}|" .env
    else
        echo "${key}=${value}" >> .env
    fi
}

# --- arguments ---------------------------------------------------------------
# --dir and --repo were consumed by the prologue above (they decide where the
# clone lands, which has already happened by the time we get here). They are
# accepted and ignored rather than rejected, so the same command line works
# whether it arrived through the pipe or was typed inside a checkout.
BIND_MODE=""
for argument in "$@"; do
    case "$argument" in
        --dir=*|--repo=*) ;;
        --bind=*) BIND_MODE="${argument#--bind=}" ;;
        --help|-h) usage; exit 0 ;;
        *) die "unknown option: $argument  (try --help)" ;;
    esac
done
case "$BIND_MODE" in
    ""|localhost|lan|tailscale|both) ;;
    *) die "--bind must be localhost, lan, tailscale or both (got '$BIND_MODE')" ;;
esac

# Every question below is a bare `read`. Piped from curl the prologue hands us
# /dev/tty so those still work, but where there is no terminal at all -- cron,
# a CI runner, a container build -- there is nothing to read from, and `read`
# would hit EOF and (under `set -e`) kill this script mid-question with no
# message. Say so here instead, while there is still nothing to clean up.
if ! [ -t 0 ]; then
    die "no terminal to ask questions on. This installer is interactive (it needs
  at least an admin email and password). Clone the repository and run it from a
  real shell:
      git clone https://github.com/dakshitha-a/NexusQC.git && cd NexusQC && scripts/install.sh"
fi

echo "${BLD}NexusQC installer${RST}"
echo "Agentic Quantum Chemistry Engine -- first-time deployment setup."

# --- 1. Preflight -----------------------------------------------------------
step "checking required tools"
for tool in git docker openssl curl; do
    command -v "$tool" >/dev/null 2>&1 || die "$tool is required but not on PATH."
done
docker compose version >/dev/null 2>&1 || die "docker compose (v2, the 'docker compose' subcommand) is required."
ok "git, docker, docker compose, openssl, curl all present"

info "Node is not needed on this host: the frontend bundle is built inside the"
info "api image and copied out by scripts/extract_frontend.sh."

# --- 2. Install location -----------------------------------------------------
step "install location"
echo "  This checkout: ${REPO_ROOT}"
echo "  All application data will live under ${REPO_ROOT}/data -- job results,"
echo "  the knowledge base, uploaded files and the molecule cache. There is no"
echo "  separate data-directory setting: wherever this clone sits is where it"
echo "  lives. Move the whole clone (stack down first) if you want it elsewhere."
ask_yn "Continue installing here?" y
[ "$ASK_YN_OK" -eq 1 ] || die "aborted -- clone NexusQC to your preferred location and re-run there."

# --- 3. .env: fresh or existing ---------------------------------------------
step "configuration (.env)"
REGEN=1
if [ -f .env ]; then
    warn "a .env already exists here."
    ask_yn "Overwrite it and reconfigure from scratch? A timestamped backup is kept." n
    if [ "$ASK_YN_OK" -eq 1 ]; then
        cp .env ".env.bak.$(date +%Y%m%d-%H%M%S)"
        ok "existing .env backed up"
    else
        REGEN=0
        ok "keeping the existing .env -- skipping to build/bring-up"
    fi
fi

if [ "$REGEN" -eq 1 ]; then
    [ -f .env.example ] || die "no .env.example in this checkout -- is this a real NexusQC clone?"
    cp .env.example .env

    step "secrets"
    PG_PASSWORD="$(openssl rand -hex 24)"
    JWT_SECRET="$(openssl rand -hex 32)"
    envset QC_AGENT_POSTGRES_PASSWORD "$PG_PASSWORD"
    envset QC_AGENT_JWT_SECRET "$JWT_SECRET"
    ok "generated a Postgres password and a JWT signing secret"

    APP_UID="$(id -u)"; APP_GID="$(id -g)"
    envset APP_UID "$APP_UID"
    envset APP_GID "$APP_GID"
    ok "container will run as this host's uid:gid (${APP_UID}:${APP_GID}) -- avoids root-owned files under data/"

    # --- 4. network exposure -------------------------------------------------
    step "network exposure"
    echo "  Localhost (127.0.0.1) is always reachable and cannot be turned off."
    echo "  You can additionally publish this stack on:"

    # --bind, when given, answers these questions instead of asking them. A
    # mode that names an address this host does not have is a refusal rather
    # than a silent downgrade to localhost: someone who typed --bind=tailscale
    # wants the tailnet, and quietly not publishing there is the kind of thing
    # nobody notices until they cannot reach the deployment from a laptop.
    want_ts=ask; want_lan=ask
    case "$BIND_MODE" in
        localhost) want_ts=no;  want_lan=no ;;
        lan)       want_ts=no;  want_lan=yes ;;
        tailscale) want_ts=yes; want_lan=no ;;
        both)      want_ts=yes; want_lan=yes ;;
    esac

    TS_IP=""
    if command -v tailscale >/dev/null 2>&1; then
        TS_IP="$(tailscale ip -4 2>/dev/null || true)"
    fi
    if [ "$want_ts" = "no" ]; then
        TS_IP=""
    elif [ -n "$TS_IP" ]; then
        if [ "$want_ts" = "yes" ]; then
            ok "publishing on the tailnet address ${TS_IP} (--bind=${BIND_MODE})"
        else
            ask_yn "  Tailscale is installed (tailnet IP ${TS_IP}) -- publish there too?" y
            [ "$ASK_YN_OK" -eq 1 ] || TS_IP=""
        fi
    elif [ "$want_ts" = "yes" ]; then
        die "--bind=${BIND_MODE} asks for the tailnet address, but Tailscale is not
  installed or is not up on this host. Install and start it, or use
  --bind=localhost or --bind=lan."
    else
        info "Tailscale not detected on this host -- skipping that option"
    fi

    LAN_IP=""
    DETECTED_LAN="$(ip route get 1.1.1.1 2>/dev/null | sed -nE 's/.*src ([0-9.]+).*/\1/p' | head -n1)"
    if [ "$want_lan" = "yes" ]; then
        [ -n "$DETECTED_LAN" ] || die "--bind=${BIND_MODE} asks for this host's LAN address, but none could be
  detected (\`ip route get 1.1.1.1\` found no source address). Run without
  --bind to enter one by hand."
        LAN_IP="$DETECTED_LAN"
        ok "publishing on the LAN address ${LAN_IP} (--bind=${BIND_MODE})"
    elif [ "$want_lan" = "ask" ]; then
        if [ -n "$DETECTED_LAN" ]; then
            ask_yn "  Publish on this host's LAN address (${DETECTED_LAN})?" n
            [ "$ASK_YN_OK" -eq 1 ] && LAN_IP="$DETECTED_LAN"
        fi
        if [ -z "$LAN_IP" ]; then
            ask_yn "  Publish on a different LAN/other address you will enter manually?" n
            if [ "$ASK_YN_OK" -eq 1 ]; then
                ask "  IP address: "
                LAN_IP="$REPLY"
            fi
        fi
    fi

    if [ -z "$TS_IP" ] && [ -z "$LAN_IP" ]; then
        info "localhost only -- nothing else will be published"
    fi

    echo
    echo "  ${BLD}This deployment serves an intranet listener and a tailnet"
    echo "  address. There is no public-internet listener.${RST}"
    echo "  The public nginx block, its port, the admin panel's public-access"
    echo "  toggle and the host firewall script were all removed on 2026-08-25:"
    echo "  the port had long been commented out, so everything built on top of"
    echo "  it was guarding a door that was not in the wall. Serving publicly"
    echo "  means restoring that listener deliberately, with a real certificate"
    echo "  and a fresh decision about access control -- git history has it."
    echo "  That is a considered step, not something to enable during a first"
    echo "  install."

    # Cert vars need real (or harmless placeholder) values regardless of what
    # gets published -- gen_intranet_cert.sh requires all three, and an unused
    # one just becomes an extra, harmless SAN entry.
    CERT_FQDN="$(hostname -f 2>/dev/null || hostname)"
    envset QC_AGENT_CERT_FQDN "$CERT_FQDN"
    envset QC_AGENT_LAN_BIND "${LAN_IP:-127.0.0.1}"
    envset QC_AGENT_TAILSCALE_BIND "${TS_IP:-127.0.0.1}"

    step "TLS certificate"
    set -a; source .env; set +a
    bash scripts/gen_intranet_cert.sh <<< "y"
    ok "self-signed certificate generated for: ${CERT_FQDN}, localhost, ${LAN_IP:-(unused)}, ${TS_IP:-(unused)}"
    warn "browsers will show a trust warning until this certificate (or a real one) is installed as trusted."

    # nginx/nginx.conf parses BOTH server blocks unconditionally, including

    # Ports override: 127.0.0.1 is always present; LAN/Tailscale are added only
    # if chosen. This fully replaces the base ports list (docker-compose.yml's
    # QC_AGENT_LAN_BIND/QC_AGENT_TAILSCALE_BIND vars still need SOME value for
    # compose to parse that file at all, which is why they are set above even
    # when unused -- but this override is what actually controls exposure.
    PORTS_YAML="      - \"127.0.0.1:8443:8443\""
    [ -n "$LAN_IP" ] && PORTS_YAML="${PORTS_YAML}
      - \"${LAN_IP}:8443:8443\""
    [ -n "$TS_IP" ] && PORTS_YAML="${PORTS_YAML}
      - \"${TS_IP}:8443:8443\""

    # --- 5. engines -----------------------------------------------------------
    step "quantum chemistry engines"
    echo "  PySCF is bundled and needs nothing here -- it covers single-point"
    echo "  energies, geometry optimisation, frequencies, TDDFT/CIS, EOM-CCSD,"
    echo "  CASSCF and orbital visualisation on its own."

    find_first() { for p in "$@"; do [ -e "$p" ] && { echo "$p"; return 0; }; done; return 1; }

    ORCA_BIN=""
    CANDIDATE="$(find_first /opt/orca*/orca 2>/dev/null || true)"
    [ -z "$CANDIDATE" ] && command -v orca >/dev/null 2>&1 && CANDIDATE="$(command -v orca)"
    if [ -n "$CANDIDATE" ]; then
        ask_yn "  Found ORCA at ${CANDIDATE} -- use it?" y
        [ "$ASK_YN_OK" -eq 1 ] && ORCA_BIN="$CANDIDATE"
    fi
    if [ -z "$ORCA_BIN" ]; then
        ask_yn "  Enter an ORCA path manually? (adds oscillator strengths for CASSCF/EOM-CCSD and NEB-TS)" n
        if [ "$ASK_YN_OK" -eq 1 ]; then
            ask "  Path to the orca binary: "
            [ -x "$REPLY" ] && ORCA_BIN="$REPLY" || warn "not an executable file -- skipping ORCA."
        else
            info "skipping ORCA -- get it from your institution's ORCA Forum academic license page"
            info "  (https://orcaforum.kofo.mpg.de/) if you want it later, then re-run this installer."
        fi
    fi

    BAGEL_BIN=""; BAGEL_SETVARS=""
    CANDIDATE="$(find_first /opt/bagel*/bin/BAGEL 2>/dev/null || true)"
    [ -z "$CANDIDATE" ] && command -v BAGEL >/dev/null 2>&1 && CANDIDATE="$(command -v BAGEL)"
    if [ -n "$CANDIDATE" ]; then
        ask_yn "  Found BAGEL at ${CANDIDATE} -- use it?" y
        [ "$ASK_YN_OK" -eq 1 ] && BAGEL_BIN="$CANDIDATE"
    fi
    if [ -z "$BAGEL_BIN" ]; then
        ask_yn "  Enter a BAGEL path manually? (adds CASPT2)" n
        if [ "$ASK_YN_OK" -eq 1 ]; then
            ask "  Path to the BAGEL binary: "
            [ -x "$REPLY" ] && BAGEL_BIN="$REPLY" || warn "not an executable file -- skipping BAGEL."
        else
            info "skipping BAGEL -- get it from https://nubakery.org/ (source) if you want it later."
        fi
    fi
    if [ -n "$BAGEL_BIN" ]; then
        CANDIDATE="$(find_first /opt/intel/oneapi/setvars.sh 2>/dev/null || true)"
        if [ -n "$CANDIDATE" ]; then
            BAGEL_SETVARS="$CANDIDATE"
            ok "found Intel oneAPI setvars.sh at ${BAGEL_SETVARS}"
        else
            ask_yn "  BAGEL needs Intel oneAPI's setvars.sh for MKL/TBB -- enter its path?" n
            if [ "$ASK_YN_OK" -eq 1 ]; then
                ask "  Path to setvars.sh: "
                [ -f "$REPLY" ] && BAGEL_SETVARS="$REPLY" || warn "file not found -- BAGEL may fail to launch without it."
            fi
        fi
    fi

    if [ -z "$ORCA_BIN" ] && [ -z "$BAGEL_BIN" ]; then
        warn "no ORCA or BAGEL configured -- this deployment will run PySCF jobs only."
    fi

    # --- 5b. Optional extras ---------------------------------------------
    #
    # Unlike ORCA and BAGEL above, block2 is an ordinary pip package with no
    # licence to chase -- it is optional purely on size. Asked rather than
    # installed by default because it is 379 MB with its own bundled MKL, and
    # the exact-FCI pilot it competes with covers every screening pool up to
    # 12 orbitals. Declining is not a degraded install: the app detects the
    # absence and stops offering the option instead of failing on it.
    step "Optional extras"
    ask_yn "  Install the DMRG entropy-pilot backend (block2)? Adds ~379 MB; lets the\n  active-space recommender screen 30 orbitals instead of 12." n
    if [ "$ASK_YN_OK" -eq 1 ]; then
        INSTALL_DMRG=1
        ok "block2 will be installed into the image"
    else
        INSTALL_DMRG=0
        info "skipping block2 -- the entropy pilot will use exact FCI only."
        info "  To add it later: set QC_AGENT_INSTALL_DMRG=1 in .env and rebuild."
    fi
    if grep -q '^QC_AGENT_INSTALL_DMRG=' .env 2>/dev/null; then
        sed -i "s|^QC_AGENT_INSTALL_DMRG=.*|QC_AGENT_INSTALL_DMRG=${INSTALL_DMRG}|" .env
    else
        printf '\n# Optional extras (see requirements-optional.txt). 1 builds the image with\n# block2, the DMRG backend for the active-space entropy pilot.\nQC_AGENT_INSTALL_DMRG=%s\n' "$INSTALL_DMRG" >> .env
    fi

    # --- 6. Ollama --------------------------------------------------------
    step "LLM (Ollama)"
    LLM_MODEL="$(sed -nE 's/^QC_AGENT_LLM_MODEL=(.*)$/\1/p' .env | tail -n1)"
    LLM_MODEL="${LLM_MODEL:-qwen3.8:27b}"
    if curl -fsS --max-time 3 http://127.0.0.1:11434/api/tags >/tmp/nexusqc_ollama_tags.$$ 2>/dev/null; then
        if grep -q "\"${LLM_MODEL}\"" /tmp/nexusqc_ollama_tags.$$ 2>/dev/null; then
            ok "Ollama is reachable and ${LLM_MODEL} is already pulled"
        else
            warn "Ollama is reachable but ${LLM_MODEL} is not pulled yet."
            ask_yn "  Pull it now (ollama pull ${LLM_MODEL})? This can take a while." y
            if [ "$ASK_YN_OK" -eq 1 ] && command -v ollama >/dev/null 2>&1; then
                ollama pull "$LLM_MODEL" || warn "pull failed -- chat will not work until a model is available."
            elif [ "$ASK_YN_OK" -eq 1 ]; then
                warn "the ollama CLI is not on PATH here -- pull it manually on the Ollama host."
            fi
        fi
    else
        warn "Ollama is not reachable at http://127.0.0.1:11434 -- chat will not work until it is running."
        warn "Install it from https://ollama.com/download, then: ollama pull ${LLM_MODEL}"
    fi
    rm -f /tmp/nexusqc_ollama_tags.$$

    # --- 7. knowledge base --------------------------------------------------
    if [ ! -d data/scraped ] || [ -z "$(ls -A data/scraped 2>/dev/null)" ]; then
        info "data/scraped is empty -- the RAG knowledge base will start EMPTY, not degraded."
        info "  Seed it later with: python3 scripts/seed_knowledge_base.py"
    fi

    # --- write docker-compose.override.yml ----------------------------------
    step "writing docker-compose.override.yml"
    {
        echo "# Generated by scripts/install.sh on $(date -Is)."
        echo "# Safe to hand-edit afterwards; re-running the installer's engine/network"
        echo "# steps will ask before overwriting this file again."
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
    } > docker-compose.override.yml
    ok "wrote docker-compose.override.yml"
fi

set -a; source .env; set +a

# --- 8. build and bring up ---------------------------------------------------
step "building images"
# Stamped here, not only in update.sh. Without it a fresh install carries
# GIT_COMMIT=unknown, which deployed_commit() reads as "cannot tell, assume
# stale" -- so the first update after an install always rebuilt everything for
# no reason, and the deployment could never say what it was running.
QC_AGENT_BUILD_COMMIT="$(git rev-parse HEAD 2>/dev/null || echo unknown)"
export QC_AGENT_BUILD_COMMIT
docker compose build || die "docker compose build failed -- see output above."
ok "images built at ${QC_AGENT_BUILD_COMMIT:0:12}"

step "installing the frontend bundle"
bash scripts/extract_frontend.sh "$QC_AGENT_BUILD_COMMIT" \
    || die "could not install the frontend bundle -- see output above."

step "starting the stack"
docker compose up -d || die "docker compose up failed -- see output above."

BASE_URL="https://127.0.0.1:8443"
HEALTHY=0
info "waiting for ${BASE_URL}/api/health"
for _ in $(seq 60); do
    if curl -fsS -k --max-time 5 "${BASE_URL}/api/health" >/dev/null 2>&1; then HEALTHY=1; break; fi
    sleep 5
done
[ "$HEALTHY" -eq 1 ] || die "the stack did not become healthy within 300s. Check: docker compose logs api"
ok "healthy at ${BASE_URL}"

# --- 9. first admin -----------------------------------------------------------
# `< /dev/null` matters here, not just for tidiness: `docker compose exec -T`
# relays this script's own stdin to the container and drains it fully before
# returning, even though `psql -c` needs no input at all -- without this
# redirect it silently swallows the admin-account answers still waiting on
# stdin below, and the next `read` hits EOF and (under `set -e`) kills the
# script with no error message right at the "Email:" prompt.
ADMIN_EXISTS="$(docker compose exec -T postgres psql -At -U "${QC_AGENT_POSTGRES_USER:-qc_agent}" -d "${QC_AGENT_POSTGRES_DB:-qc_agent}" -c "SELECT count(*) FROM users WHERE role='admin'" < /dev/null 2>/dev/null || echo "0")"
if [ "${ADMIN_EXISTS:-0}" -gt 0 ] 2>/dev/null; then
    ok "an admin account already exists -- skipping bootstrap"
else
    step "primary admin account"
    ask "  Email: "; ADMIN_EMAIL="$REPLY"
    ask "  Username: "; ADMIN_USERNAME="$REPLY"
    ask "  First name: "; ADMIN_FIRST="$REPLY"
    ask "  Last name: "; ADMIN_LAST="$REPLY"
    while :; do
        read -r -s -p "  Password (min 8 characters): " ADMIN_PASS; echo >&2
        read -r -s -p "  Confirm password: " ADMIN_PASS2; echo >&2
        [ "$ADMIN_PASS" = "$ADMIN_PASS2" ] || { warn "passwords did not match -- try again."; continue; }
        [ "${#ADMIN_PASS}" -ge 8 ] || { warn "password must be at least 8 characters -- try again."; continue; }
        break
    done
    printf '%s\n' "$ADMIN_PASS" | docker compose exec -T api python -m server.admin_cli bootstrap-admin \
        --email "$ADMIN_EMAIL" --username "$ADMIN_USERNAME" \
        --first-name "$ADMIN_FIRST" --last-name "$ADMIN_LAST" --password-stdin \
        || die "admin bootstrap failed -- see output above."
    ok "admin account created: ${ADMIN_USERNAME} <${ADMIN_EMAIL}>"
fi

# --- 10. summary ---------------------------------------------------------------
step "done"
echo "  ${GRN}NexusQC is up.${RST}"
echo "  Reachable at:"
echo "    https://127.0.0.1:8443  (always on)"
[ -n "${LAN_IP:-}" ] && echo "    https://${LAN_IP}:8443  (LAN)"
[ -n "${TS_IP:-}" ] && echo "    https://${TS_IP}:8443  (Tailscale)"
echo
echo "  The certificate is self-signed -- your browser will warn once per client"
echo "  machine until you accept it or install a trusted certificate instead."
echo "  Application data lives under: ${REPO_ROOT}/data"
if [ -z "${ORCA_BIN:-}" ] && [ -z "${BAGEL_BIN:-}" ]; then
    echo "  Only PySCF calculations are available -- re-run this installer after"
    echo "  installing ORCA/BAGEL to add them."
fi
echo
echo "  Back up this deployment with: scripts/backup.sh --full"
echo "  Update it later with:         scripts/update.sh"

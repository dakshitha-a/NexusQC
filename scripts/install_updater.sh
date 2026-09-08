#!/usr/bin/env bash
# Install (or remove) the systemd --user units that let the admin panel run an
# update on this host.
#
# WHAT THIS IS FOR
# ----------------
# The api container cannot update its own deployment, and giving it a docker
# socket to do so would make any bug in a multi-user web app a host-root bug.
# Instead the api writes a request into data/deploy and something on the host
# picks it up. This installs that something.
#
# It is a .path unit watching for the request file, triggering a oneshot
# service -- not a daemon polling in a loop. systemd already knows how to watch
# a path, restart the unit if it dies, and start it at boot, and a unit that
# only runs when there is work to do cannot leak a process.
#
# WITHOUT THIS the admin panel still works: it reports what is deployed, who is
# mid-calculation, and what an update would break. It just shows the host
# command instead of an Apply button. That is the honest degradation, and it is
# why this is a separate opt-in script rather than something install.sh does
# silently.
#
# Usage:
#     scripts/install_updater.sh            # install and start
#     scripts/install_updater.sh --remove   # stop and remove
#     scripts/install_updater.sh --status
set -eu

SELF_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SELF_DIR/.." && pwd)"
cd "$REPO_ROOT"

RED=$'\033[31m'; GRN=$'\033[32m'; YEL=$'\033[33m'; DIM=$'\033[2m'; RST=$'\033[0m'
if [ ! -t 1 ]; then RED=''; GRN=''; YEL=''; DIM=''; RST=''; fi
die()  { echo "${RED}install_updater: $*${RST}" >&2; exit 1; }
ok()   { echo "${GRN}  ok${RST}  $*"; }
info() { echo "${DIM}  ..${RST}  $*"; }
warn() { echo "${YEL}  !!${RST}  $*"; }

# One host can run several checkouts of this repository -- a live deployment, a
# development copy, a scratch install. A unit called plainly "nexusqc-updater"
# would collide across them, and the second install would silently retarget the
# first. The suffix is a hash of the absolute path, so a name is stable for a
# checkout and distinct between checkouts.
SUFFIX="$(printf '%s' "$REPO_ROOT" | sha256sum | cut -c1-8)"
UNIT="nexusqc-updater-${SUFFIX}"
UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"

ACTION=install
case "${1:-}" in
    --remove) ACTION=remove ;;
    --status) ACTION=status ;;
    "") ;;
    *) die "unknown argument: $1 (try --remove or --status)" ;;
esac

have_systemd() {
    command -v systemctl >/dev/null 2>&1 && systemctl --user show-environment >/dev/null 2>&1
}

if [ "$ACTION" = "status" ]; then
    echo "checkout:  $REPO_ROOT"
    echo "unit:      ${UNIT}.path"
    if have_systemd; then
        systemctl --user status "${UNIT}.path" --no-pager 2>&1 | head -6 || true
    else
        echo "systemd --user is not available here"
    fi
    exit 0
fi

if [ "$ACTION" = "remove" ]; then
    if have_systemd; then
        systemctl --user disable --now "${UNIT}.path" >/dev/null 2>&1 || true
        systemctl --user stop "${UNIT}.service" >/dev/null 2>&1 || true
    fi
    rm -f "${UNIT_DIR}/${UNIT}.path" "${UNIT_DIR}/${UNIT}.service"
    have_systemd && systemctl --user daemon-reload >/dev/null 2>&1 || true
    rm -f data/deploy/runner.json
    ok "removed ${UNIT} and its heartbeat"
    exit 0
fi

have_systemd || die "systemd --user is not available on this host (no systemctl, or no user bus).
  The admin panel will still report what is deployed and what an update would
  break; it will show the host command instead of an Apply button. Run updates
  with: cd ${REPO_ROOT} && scripts/update.sh"

command -v docker >/dev/null 2>&1 || die "docker is required."
mkdir -p "$UNIT_DIR" data/deploy

# The PATH is written out in full on purpose. Under `systemd --user` it is
# minimal, and this unit shells out to git, docker and python3.
UNIT_PATH_ENV="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:${HOME}/.local/bin"

cat > "${UNIT_DIR}/${UNIT}.path" <<EOF
[Unit]
Description=NexusQC deployment requests (${REPO_ROOT})

[Path]
# Fires when the api writes a request. The service's first act is to move the
# file out of the way -- a .path unit triggers on the file EXISTING, so leaving
# it in place would mean it never fires again.
PathExists=${REPO_ROOT}/data/deploy/request.json
Unit=${UNIT}.service

[Install]
WantedBy=default.target
EOF

cat > "${UNIT_DIR}/${UNIT}.service" <<EOF
[Unit]
Description=NexusQC deployment runner (${REPO_ROOT})

[Service]
Type=oneshot
WorkingDirectory=${REPO_ROOT}
Environment=PATH=${UNIT_PATH_ENV}
Environment=HOME=${HOME}
ExecStart=/bin/bash ${REPO_ROOT}/scripts/deploy_runner.sh
# An update legitimately takes a long time: a drain waits for running jobs,
# and QC_AGENT_DRAIN_TIMEOUT defaults to four hours because a CASSCF run here
# is not an outlier. A shorter timeout would kill the runner mid-update.
TimeoutStartSec=0

[Install]
WantedBy=default.target
EOF

systemctl --user daemon-reload
systemctl --user enable --now "${UNIT}.path" >/dev/null 2>&1 \
    || die "could not enable ${UNIT}.path -- see: systemctl --user status ${UNIT}.path"
ok "installed and started ${UNIT}.path"

# Write the first heartbeat now, so the panel does not have to wait for a
# request before it can tell the runner is there.
bash scripts/deploy_runner.sh >/dev/null 2>&1 || true
[ -f data/deploy/runner.json ] && ok "runner heartbeat written" || warn "no heartbeat yet"

loginctl enable-linger "$(id -un)" >/dev/null 2>&1 \
    || info "run 'sudo loginctl enable-linger $(id -un)' if updates should work while you are logged out"

echo
echo "  The admin panel's Deployment section can now run updates on this host."
echo "  Remove it again with: scripts/install_updater.sh --remove"

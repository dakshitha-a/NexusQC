#!/usr/bin/env bash
# Host-level kill switch for the public-facing nginx listener -- the
# mechanism that works even if the application itself (api/postgres/redis/
# nginx) is completely unresponsive, because it never talks to any of
# them. This is deliberately separate from the app-level "soft" toggle
# (POST /api/admin/toggle-public-access, app/auth/middleware.py) -- that
# one is fast and graceful (a clean 503 with an explanation) but depends
# on the application actually being up to serve it; this one is a raw
# firewall rule a sysadmin runs with their own shell access, independent
# of whether anything above the network layer is healthy.
#
# Requires root (uses iptables directly). Run this ON THE HOST, not inside
# a container -- it manages the host's own firewall, not anything docker-
# compose brings up.
#
# Usage:
#   sudo ./scripts/toggle_public_access.sh on|off|status
#
# What "off" actually does: inserts a DROP rule for inbound traffic to the
# public nginx listener's port (default 443, override via
# QC_AGENT_PUBLIC_PORT) from any source. The intranet listener (a
# different port, published only on this host's LAN and tailnet addresses
# -- see nginx/nginx.conf and docker-compose.yml) is never touched by this
# script, matching the deployment requirement that the two access paths
# are controlled independently.
#
# WHY TWO CHAINS, NOT JUST INPUT
# ------------------------------
# An earlier version of this script inserted into the INPUT chain only.
# Against a Docker-published port that rule matches nothing at all, and the
# switch silently did nothing while reporting success -- the worst possible
# failure mode for a kill switch.
#
# The reason: Docker publishes a container port with a DNAT rule in the nat
# table's PREROUTING chain. Once the destination has been rewritten to the
# container's own address, the packet is no longer destined for this host,
# so it is routed rather than delivered locally -- it traverses FORWARD, and
# never enters INPUT. Docker provides the DOCKER-USER chain, evaluated
# before its own generated rules and preserved across daemon restarts,
# precisely for administrator rules on that path. That is where the
# effective rule has to go.
#
# INPUT is still handled as well, because it is not entirely irrelevant: a
# connection originating on this host itself reaches the published port
# through Docker's userland proxy, which is a real local process and does
# use the INPUT path. Covering both means "off" means off regardless of
# where the client is.
set -euo pipefail

PORT="${QC_AGENT_PUBLIC_PORT:-443}"
CHAIN_COMMENT="qc-agent-public-access-toggle"
# DOCKER-USER is created by the Docker daemon. If it is absent, Docker has
# never started on this host and there is no published port to block.
CHAINS="DOCKER-USER INPUT"

if [ "$(id -u)" -ne 0 ]; then
    echo "This script modifies host firewall rules and must be run as root (sudo)." >&2
    exit 1
fi

if ! command -v iptables >/dev/null 2>&1; then
    echo "iptables not found on this host. This script targets iptables specifically;" >&2
    echo "if this host uses nftables/ufw/firewalld instead, adapt the rule below to that" >&2
    echo "tool's equivalent of 'drop all inbound traffic to tcp/\$PORT'." >&2
    exit 1
fi

_chain_exists() {
    iptables -L "$1" -n >/dev/null 2>&1
}

_existing_rule_line() {
    # First line number of this script's own rule in the given chain, or
    # empty. Matched on the comment, never on position.
    iptables -L "$1" -n --line-numbers 2>/dev/null \
        | grep "$CHAIN_COMMENT" | awk '{print $1}' | head -1 || true
}

_blocked_anywhere() {
    for c in $CHAINS; do
        _chain_exists "$c" || continue
        [ -n "$(_existing_rule_line "$c")" ] && return 0
    done
    return 1
}

case "${1:-}" in
    off)
        acted=0
        for c in $CHAINS; do
            if ! _chain_exists "$c"; then
                echo "note: chain $c does not exist on this host -- skipping." >&2
                continue
            fi
            if [ -n "$(_existing_rule_line "$c")" ]; then
                echo "  $c: already blocked."
            else
                # -I inserts at position 1, ahead of Docker's own generated
                # ACCEPT rules -- appending would land after them and never
                # be reached.
                iptables -I "$c" 1 -p tcp --dport "$PORT" -j DROP \
                    -m comment --comment "$CHAIN_COMMENT"
                echo "  $c: blocked."
                acted=1
            fi
        done
        [ "$acted" -eq 1 ] && echo "Public access to port $PORT is now OFF. The intranet listener is unaffected."
        ;;
    on)
        removed=0
        for c in $CHAINS; do
            _chain_exists "$c" || continue
            line="$(_existing_rule_line "$c")"
            # Re-query after each delete: line numbers shift once a rule is
            # removed, so deleting a stale cached number could remove an
            # unrelated rule.
            while [ -n "$line" ]; do
                iptables -D "$c" "$line"
                removed=1
                line="$(_existing_rule_line "$c")"
            done
        done
        if [ "$removed" -eq 1 ]; then
            echo "Public access to port $PORT restored."
        else
            echo "Public access to port $PORT was not blocked -- nothing to do."
        fi
        ;;
    status)
        for c in $CHAINS; do
            if ! _chain_exists "$c"; then
                echo "  $c: chain absent"
            elif [ -n "$(_existing_rule_line "$c")" ]; then
                echo "  $c: DROP rule present"
            else
                echo "  $c: no rule"
            fi
        done
        if _blocked_anywhere; then
            echo "BLOCKED: public access to port $PORT is currently off."
        else
            echo "OPEN: no block rule is in place for port $PORT."
            echo "Note: as deployed, docker-compose.yml does not publish port ${PORT} at all,"
            echo "so 'OPEN' here does not by itself mean the port is reachable."
        fi
        ;;
    *)
        echo "Usage: sudo $0 on|off|status" >&2
        exit 1
        ;;
esac

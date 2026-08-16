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
# different port, bound only to the host's internal interface -- see
# nginx/nginx.conf and QC_AGENT_INTRANET_BIND) is never touched by this
# script, matching the deployment requirement that the two access paths
# are controlled independently.
set -euo pipefail

PORT="${QC_AGENT_PUBLIC_PORT:-443}"
CHAIN_COMMENT="qc-agent-public-access-toggle"

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

_existing_rule_line() {
    iptables -L INPUT -n --line-numbers | grep "$CHAIN_COMMENT" | awk '{print $1}' || true
}

case "${1:-}" in
    off)
        if [ -n "$(_existing_rule_line)" ]; then
            echo "Public access to port $PORT is already blocked."
        else
            iptables -I INPUT -p tcp --dport "$PORT" -j DROP -m comment --comment "$CHAIN_COMMENT"
            echo "Blocked all inbound traffic to port $PORT. The campus intranet listener is unaffected."
        fi
        ;;
    on)
        line="$(_existing_rule_line)"
        if [ -n "$line" ]; then
            # Re-check after each delete: line numbers shift once a rule
            # is removed, so re-querying rather than deleting a stale
            # cached line number avoids deleting the wrong rule if more
            # than one match ever exists.
            while [ -n "$line" ]; do
                iptables -D INPUT "$line"
                line="$(_existing_rule_line)"
            done
            echo "Public access to port $PORT restored."
        else
            echo "Public access to port $PORT was not blocked -- nothing to do."
        fi
        ;;
    status)
        if [ -n "$(_existing_rule_line)" ]; then
            echo "BLOCKED: public access to port $PORT is currently off."
        else
            echo "OPEN: public access to port $PORT is currently allowed (subject to whatever else -- docker-compose.yml's port mapping, an upstream router -- actually exposes it)."
        fi
        ;;
    *)
        echo "Usage: sudo $0 on|off|status" >&2
        exit 1
        ;;
esac

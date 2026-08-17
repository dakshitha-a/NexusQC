#!/usr/bin/env bash
# Generates the self-signed TLS certificate the nginx intranet listener
# serves, with the subjectAltName entries a modern browser actually
# requires.
#
# Why this script exists rather than a one-line openssl invocation in the
# runbook: the certificate this replaced was generated ad hoc during the
# auth/admin QA pass with `CN=127.0.0.1`, no subjectAltName at all, and a
# 30-day lifetime. Every browser released in the last several years ignores
# the Common Name field entirely for hostname verification (RFC 2818's CN
# fallback was removed) and validates against subjectAltName only -- so that
# certificate did not merely warn, it failed outright with
# ERR_CERT_COMMON_NAME_INVALID and offered no click-through on some
# configurations. Getting the SAN list right is the whole job, which makes
# it worth a checked-in script that records the intended list.
#
# Run from the repository root:
#     ./scripts/gen_intranet_cert.sh
#
# Overwrites nginx/certs/intranet.{crt,key}. Reload nginx afterwards:
#     docker compose exec nginx nginx -s reload
#
# REPLACING THIS WITH AN INSTITUTIONAL CERTIFICATE
# ------------------------------------------------
# Nothing here is load-bearing for the rest of the deployment. If a
# Temple/InCommon certificate for this host becomes available, drop the
# issued certificate and its private key in as nginx/certs/intranet.crt and
# nginx/certs/intranet.key (concatenate any intermediate chain onto the end
# of the .crt, leaf first), chmod 600 the key, reload nginx, and stop
# running this script. No other file changes.
set -euo pipefail

cd "$(dirname "$0")/.."

CERT_DIR="nginx/certs"
DAYS="${QC_AGENT_CERT_DAYS:-3650}"

# The identities a browser may be asked to verify. All three matter:
#   - the FQDN, for anyone using the hostname
#   - the lab LAN address, which is what docker-compose.yml publishes on
#   - the tailnet address, the second published bind
#   - loopback, for host-local curl checks and the deployment's own smoke
#     tests, which would otherwise need --insecure and thereby stop
#     testing the thing they are meant to test
FQDN="${QC_AGENT_CERT_FQDN:-qchost.example.invalid}"
LAN_IP="${QC_AGENT_LAN_BIND:-10.0.0.10}"
TS_IP="${QC_AGENT_TAILSCALE_BIND:-100.64.0.10}"

SAN="DNS:${FQDN},DNS:localhost,IP:${LAN_IP},IP:${TS_IP},IP:127.0.0.1"

if [ -f "${CERT_DIR}/intranet.crt" ]; then
    echo "Existing certificate:"
    openssl x509 -in "${CERT_DIR}/intranet.crt" -noout -subject -dates 2>/dev/null | sed 's/^/    /'
    printf 'Overwrite it? [y/N] '
    read -r reply
    case "$reply" in
        [yY]*) ;;
        *) echo "Aborted -- nothing changed."; exit 0 ;;
    esac
fi

mkdir -p "$CERT_DIR"

echo "Generating a ${DAYS}-day self-signed certificate"
echo "  subject: CN=${FQDN}"
echo "  SANs:    ${SAN}"

# -noenc (formerly -nodes): the key must be usable by nginx unattended at
# container start. A passphrase-protected key would block startup on a
# prompt nothing is there to answer, including after an unattended reboot.
openssl req -x509 -newkey rsa:4096 -noenc \
    -keyout "${CERT_DIR}/intranet.key" \
    -out "${CERT_DIR}/intranet.crt" \
    -days "$DAYS" \
    -subj "/C=US/ST=Pennsylvania/L=Philadelphia/O=Temple University/OU=NexusQC/CN=${FQDN}" \
    -addext "subjectAltName=${SAN}" \
    -addext "basicConstraints=critical,CA:FALSE" \
    -addext "keyUsage=critical,digitalSignature,keyEncipherment" \
    -addext "extendedKeyUsage=serverAuth" \
    2>/dev/null

chmod 600 "${CERT_DIR}/intranet.key"
chmod 644 "${CERT_DIR}/intranet.crt"

echo
echo "Wrote ${CERT_DIR}/intranet.crt and ${CERT_DIR}/intranet.key"
openssl x509 -in "${CERT_DIR}/intranet.crt" -noout -subject -dates -ext subjectAltName | sed 's/^/    /'
echo
echo "Next: docker compose exec nginx nginx -s reload"
echo "Browsers will still show a warning until this certificate is trusted"
echo "on each client machine -- see docs/DEPLOYMENT.md for the import step."

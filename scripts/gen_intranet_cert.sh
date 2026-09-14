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
# certificate for this host issued by a CA your users already trust becomes
# available -- an institutional one, or one from a public CA -- drop the
# issued certificate and its private key in as nginx/certs/intranet.crt and
# nginx/certs/intranet.key (concatenate any intermediate chain onto the end
# of the .crt, leaf first), chmod 600 the key, reload nginx, and stop
# running this script. No other file changes.
set -euo pipefail

cd "$(dirname "$0")/.."

die() { echo "gen_intranet_cert: $*" >&2; exit 1; }

CERT_DIR="nginx/certs"
DAYS="${QC_AGENT_CERT_DAYS:-3650}"

# The identities a browser may be asked to verify. All three matter:
#   - the FQDN, for anyone using the hostname
#   - the lab LAN address, which is what docker-compose.yml publishes on
#   - the tailnet address, the second published bind
#   - loopback, for host-local curl checks and the deployment's own smoke
#     tests, which would otherwise need --insecure and thereby stop
#     testing the thing they are meant to test
# No defaults on purpose. A wrong-but-plausible default here mints a
# certificate whose SAN does not match the address anyone actually uses, and
# the failure surfaces later as an opaque browser trust error rather than as
# the missing configuration it really is. Set these in .env.
# No apostrophes in these messages. Inside ${VAR:?word} the word is still
# quote-processed, so a lone apostrophe opens a single-quoted string and the
# whole script dies with "unexpected EOF while looking for matching quote"
# instead of printing the message -- caught by running it, not by reading it.
: "${QC_AGENT_CERT_FQDN:?set QC_AGENT_CERT_FQDN to the FQDN of this host (see .env.example)}"
: "${QC_AGENT_LAN_BIND:?set QC_AGENT_LAN_BIND to the internal LAN IP of this host (see .env.example)}"
: "${QC_AGENT_TAILSCALE_BIND:?set QC_AGENT_TAILSCALE_BIND to the tailnet IP of this host (see .env.example)}"
FQDN="$QC_AGENT_CERT_FQDN"
LAN_IP="$QC_AGENT_LAN_BIND"
TS_IP="$QC_AGENT_TAILSCALE_BIND"

# Built by appending only what is not already there. The LAN and tailnet
# variables are required to hold *some* value -- docker-compose.yml will not
# parse without them -- so a deployment that publishes on neither sets both to
# 127.0.0.1, and a naive list then mints a certificate whose SAN reads
# "IP Address:127.0.0.1, IP Address:127.0.0.1, IP Address:127.0.0.1". Harmless,
# and it looks exactly like a bug to anyone who inspects the certificate.
SAN=""
san_add() {
    case ",${SAN}," in *",$1,"*) return 0 ;; esac
    SAN="${SAN:+${SAN},}$1"
}
san_add "DNS:${FQDN}"
san_add "DNS:localhost"
san_add "IP:${LAN_IP}"
san_add "IP:${TS_IP}"
san_add "IP:127.0.0.1"
# The public address (QC_AGENT_PUBLIC_URL) is what invite and reset links
# carry, so whoever follows one types its host; if that is a name other than
# the FQDN it has to verify too. An IP there is already covered or is one of
# the binds; only a name is added.
PUBLIC_HOST="$(printf '%s\n' "${QC_AGENT_PUBLIC_URL:-}" | sed -nE 's#^[a-zA-Z][a-zA-Z0-9+.-]*://([^/:?\#]+).*$#\1#p')"
case "$PUBLIC_HOST" in
    "") ;;
    *[!0-9.]*) san_add "DNS:${PUBLIC_HOST}" ;;
    *) ;;
esac

# The subject is the common name and nothing else. It used to carry a fixed
# country, state, locality and organisation, which meant every deployment
# anyone stood up anywhere minted a certificate claiming to belong to one
# particular university. None of those fields is consulted by anything: a
# browser validates an intranet certificate against subjectAltName alone, and
# has ignored the Common Name for hostname verification for years (see the
# note at the top of this file). So they were decoration that could only ever
# be wrong for somebody.

# QC_CERT_DRIVEN says a script is running this, not a person: scripts/install.sh
# sets it while reconfiguring a deployment. That caller has already decided to
# mint a new certificate and has already asked about the name, so asking again
# here has nobody to answer it. It used to be answered with a `<<< "y"`
# here-string, which meant the install printed "Overwrite it? [y/N] " with no
# visible reply and then carried on -- the installer appearing to interrogate
# itself, mid-install.
if [ -f "${CERT_DIR}/intranet.crt" ]; then
    echo "Existing certificate:"
    openssl x509 -in "${CERT_DIR}/intranet.crt" -noout -subject -dates 2>/dev/null | sed 's/^/    /'
    if [ -n "${QC_CERT_DRIVEN:-}" ]; then
        echo "Replacing it."
    else
        printf 'Overwrite it? [y/N] '
        read -r reply
        case "$reply" in
            [yY]*) ;;
            *) echo "Aborted -- nothing changed."; exit 0 ;;
        esac
    fi
fi

mkdir -p "$CERT_DIR"

echo "Generating a ${DAYS}-day self-signed certificate"
echo "  subject: CN=${FQDN}"
echo "  SANs:    ${SAN}"

# -noenc (formerly -nodes): the key must be usable by nginx unattended at
# container start. A passphrase-protected key would block startup on a
# prompt nothing is there to answer, including after an unattended reboot.
# stderr is held rather than discarded, and shown only if this fails. It used to
# go to /dev/null, which also threw away the reason -- and the most likely
# reason, a hostname where the SAN needs a literal IP, then killed the caller in
# complete silence. Simply letting it through instead would print several lines
# of key-generation progress dots on every successful install.
CERT_ERR="$(mktemp)"
if ! openssl req -x509 -newkey rsa:4096 -noenc \
    -keyout "${CERT_DIR}/intranet.key" \
    -out "${CERT_DIR}/intranet.crt" \
    -days "$DAYS" \
    -subj "/CN=${FQDN}" \
    -addext "subjectAltName=${SAN}" \
    -addext "basicConstraints=critical,CA:FALSE" \
    -addext "keyUsage=critical,digitalSignature,keyEncipherment" \
    -addext "extendedKeyUsage=serverAuth" \
    2>"$CERT_ERR"; then
    sed 's/^/    /' "$CERT_ERR" >&2
    rm -f "$CERT_ERR"
    die "openssl could not generate the certificate. The most likely cause is an
  entry in the SAN list above that is not what it claims to be -- a hostname
  where QC_AGENT_LAN_BIND or QC_AGENT_TAILSCALE_BIND needs a literal IP address.
  openssl's own error is immediately above this message."
fi
rm -f "$CERT_ERR"

chmod 600 "${CERT_DIR}/intranet.key"
chmod 644 "${CERT_DIR}/intranet.crt"

echo
echo "Wrote ${CERT_DIR}/intranet.crt and ${CERT_DIR}/intranet.key"
openssl x509 -in "${CERT_DIR}/intranet.crt" -noout -subject -dates -ext subjectAltName | sed 's/^/    /'
echo
# Suppressed under QC_CERT_DRIVEN, because scripts/install.sh is about to start
# nginx itself: there is no running container to reload, and being told to
# reload one is confusing at exactly the wrong moment.
if [ -z "${QC_CERT_DRIVEN:-}" ]; then
    echo "Next: docker compose exec nginx nginx -s reload"
    echo "Browsers will still show a warning until this certificate is trusted"
    echo "on each client machine -- see docs/DEPLOYMENT.md for the import step."
fi

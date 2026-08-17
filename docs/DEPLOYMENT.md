# Deployment guide

Running NexusQC as a multi-user service with real accounts, per-user data
isolation, an admin console, and HTTPS.

If you only want NexusQC on your own machine, you do not need any of this — see
the Quickstart in the [README](../README.md). Single-user mode has no login and
no database.

**The switch between the two modes is a single environment variable.** Setting
`QC_AGENT_DATABASE_URL` activates the entire auth layer: without it, none of the
auth or admin routes are even mounted and the checkpointer stays on SQLite.

---

## Before you start

You need:

| Requirement | Check it with | Notes |
|---|---|---|
| Docker Engine + Compose v2 | `docker compose version` | Compose v2 syntax (`docker compose`, not `docker-compose`) |
| A hostname or LAN IP to serve on | `ip -4 addr show \| grep inet` | Used for the intranet listener |
| A TLS certificate | — | **Mandatory.** See below — login silently fails over plain HTTP |
| ORCA and/or BAGEL *(optional)* | — | Never bundled; bind-mounted from the host |
| NVIDIA Container Toolkit *(optional)* | `docker info \| grep -i nvidia` | Only for the optional vLLM backend |

Pinned service versions, all set in `docker-compose.yml`: Postgres 16, Redis 7,
nginx 1.27, `python:3.11-slim-bookworm` for the API image.

> **The Debian pin is deliberate.** The unpinned `python:3.11-slim` tag drifted
> to Debian 13, whose repositories carry only OpenMPI 5.x — which dropped the
> C++ bindings library BAGEL links against, with no compatibility package
> available. Debian 12's OpenMPI 4.1.x has it. Do not "modernise" this pin
> without testing a real BAGEL job.

---

## 1. Get the code

```bash
git clone https://github.com/dakshitha-a/NexusQC.git
cd NexusQC
```

## 2. Create your configuration

```bash
cp .env.example .env
```

Now edit `.env`. Three values must be changed before anything will start:

```bash
# Generate a strong Postgres password
python3 -c "import secrets; print(secrets.token_urlsafe(24))"

# Generate a JWT signing secret (must be at least 32 bytes)
python3 -c "import secrets; print(secrets.token_urlsafe(32))"

# Find this host's LAN IP for the intranet listener
ip -4 addr show | grep inet | grep -v 127.0.0.1
```

Set in `.env`:

- `QC_AGENT_POSTGRES_PASSWORD` — the first generated value
- `QC_AGENT_JWT_SECRET` — the second generated value
- `QC_AGENT_INTRANET_BIND` — the LAN IP you found (e.g. `192.168.1.50`)

Also set the file-ownership variables, so the container writes into `./data` as
**you** rather than as root — otherwise job artifacts and uploads end up owned by
a uid you cannot delete without `sudo`:

```bash
echo "APP_UID=$(id -u)" >> .env
echo "APP_GID=$(id -g)" >> .env
```

## 3. Provide a TLS certificate

**Both nginx listeners must use HTTPS.** The session cookie is marked `Secure`,
so over plain HTTP login appears to do nothing at all — no error, just a form
that never proceeds. This is the single most common first-deployment failure.

Nothing generates the certificate for you; `nginx/nginx.conf` expects the files
to already exist.

For an intranet deployment, a self-signed certificate is fine:

```bash
mkdir -p nginx/certs
openssl req -x509 -nodes -days 825 -newkey rsa:2048 \
  -keyout nginx/certs/intranet.key \
  -out nginx/certs/intranet.crt \
  -subj "/CN=$(hostname -f)" \
  -addext "subjectAltName=DNS:$(hostname -f),IP:<YOUR_LAN_IP>"
```

Replace `<YOUR_LAN_IP>` with the address you put in `.env`. Browsers will warn
about the self-signed certificate; that is expected on an intranet.

For a **public** listener, use a real certificate from a certificate authority
(certbot / Let's Encrypt). Provisioning that is outside this repository's scope.

## 4. Enable ORCA / BAGEL (optional)

Skip this if you only need PySCF, which is installed inside the image and covers
most calculation types.

ORCA and BAGEL are **never** bundled into any image — ORCA's licence explicitly
forbids redistribution, and both are treated the same way regardless. They are
bind-mounted read-only from wherever they already live on your host.

```bash
cp docker-compose.override.yml.example docker-compose.override.yml
```

Edit that file so both the `volumes:` paths and the matching `QC_AGENT_*_BIN`
environment variables point at your real installs. Use the **same absolute path**
on both sides of each mount, so one value works for both the container and any
bare-metal run.

BAGEL additionally needs its Intel oneAPI environment; `docker/entrypoint.sh`
sources it automatically if the oneAPI directory is mounted, and skips it
harmlessly with a log line if you do not use BAGEL.

## 5. Build and start

```bash
docker compose build
docker compose up -d postgres redis
```

Wait a few seconds for Postgres to accept connections, then bring up the rest:

```bash
docker compose up -d
```

**Check it came up:**

```bash
docker compose ps          # every service should be "running"
docker compose logs -f api # should end with uvicorn listening on 0.0.0.0:8000
```

## 6. Build the frontend

This step is easy to miss and produces a confusing result if skipped.

**nginx serves `frontend/dist` from a host bind mount**, completely independent
of whatever frontend build is inside the API image. `docker compose build` does
**not** refresh it. A stale `frontend/dist` means the deployed UI is an old build
even though everything else succeeded.

```bash
conda activate node24   # or any Node >= 24.14.1
cd frontend && npm ci && npm run build && cd ..
```

Node 24 is a hard requirement — it is what Ketcher, the 2D structure editor,
declares in its `engines` field.

## 7. Create the first admin account

This is deliberately a filesystem-local command rather than a web form: the whole
point is that it requires shell access to the host, not a web credential.

```bash
docker compose run --rm api python -m server.admin_cli bootstrap-admin \
  --email you@yourlab.edu --username admin
```

It will prompt for a password and print confirmation. This refuses to run if any
admin account already exists.

## 8. Log in

Open `https://<your-LAN-IP>:8443` and sign in with the account you just created.
Accept the self-signed certificate warning.

New users join by invite token, generated by an admin — there is no open
registration.

---

## Upgrading a deployment that previously ran as root

Everything already under `data/` is root-owned, and the non-root container cannot
write to it, so the first molecule lookup or job submission fails with
`PermissionError`. Fix it once, before `docker compose up`:

```bash
docker run --rm -v "$PWD/data:/d" alpine chown -R "$(id -u):$(id -g)" /d
```

---

## Day-to-day administration

Most administration happens in the React admin console, reachable from the
account bar in the top-right corner when logged in as an admin. It covers
storage quotas, the live usage readout, concurrency caps, bulk purges, the audit
log and the public-access toggle.

Two things the console does **not** cover yet — user and invite-token management,
and the bug-report inbox — go through the API. These examples assume a cookie jar
saved by logging in first:

```bash
# Log in and save the session cookie
curl -s -c admin_cookies.txt -X POST https://<host>/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username": "admin", "password": "<your-password>"}'

# Generate an invite token (role: "user" or "admin")
curl -s -b admin_cookies.txt -X POST https://<host>/api/admin/invites \
  -H "Content-Type: application/json" -d '{"role": "user"}'

# List users with usage stats
curl -s -b admin_cookies.txt https://<host>/api/admin/users

# Read or change quotas
curl -s -b admin_cookies.txt https://<host>/api/admin/config
curl -s -b admin_cookies.txt -X PATCH https://<host>/api/admin/config \
  -H "Content-Type: application/json" \
  -d '{"key": "per_user_kb_quota_bytes", "value": 5000000000}'

# The append-only action history
curl -s -b admin_cookies.txt https://<host>/api/admin/audit-log
```

### If every admin is locked out

Recover with the filesystem-local CLI. This requires shell access to the host,
by design — it exists precisely for when no web authentication path works.

```bash
# Clears users, sessions and invite tokens. Job/thread/KB data under ./data
# is preserved unless you add --wipe-data. The audit log and bug reports
# survive with their user references nulled.
docker compose run --rm api python -m server.admin_cli reset-all --confirm

# Then bootstrap a fresh admin, as in step 7.
```

---

## Storage quotas

Storage is capped and self-evicting, oldest-first, in three categories:

| Category | Default | Scope |
|---|---|---|
| Knowledge-base uploads | 2 GB | Per user |
| Job artifacts **and** chat history | 18 GB | Per user, **one shared pool** |
| Everything, all users combined | 200 GB | Global — a single cap, not per-category |

Concurrency is capped separately, and is also editable at runtime from the
console or `PATCH /api/admin/config`:

| Limit | Default | Notes |
|---|---|---|
| Concurrent jobs, all users | 20 | Clamped to `QC_AGENT_MAX_CONCURRENT_JOBS`, which fixes the worker-pool size at process start and cannot be resized live |
| Concurrent jobs, per user | 5 | Stops one user monopolising the queue |
| Cores per job | 4 | `QC_AGENT_N_CORES`. Per-job width, not a total — 20 × 4 = up to 80 cores in flight |

NexusQC does not reserve a fixed slice of the machine: every core is available,
and the host-load admission gate is what prevents oversubscription. Raise
`QC_AGENT_N_CORES` for wide single jobs, lower it to favour many small ones —
but see the warning in [CONFIGURATION.md](CONFIGURATION.md#job-execution-and-resource-limits)
about setting it near your total core count.

Eviction runs oldest-first after every job submission and knowledge-base upload,
and every ~5 minutes from the background watcher to catch chat-history growth,
which has no per-message hook. A pending or running job and the pre-seeded manual
corpus are never evicted.

Every quota change and every purge, automatic or manual, is written to an audit
log that is **genuinely append-only** — a Postgres trigger rejects `UPDATE`,
`DELETE` and `TRUNCATE` outright, rather than merely having no route that exposes
one.

---

## Intranet and public access

Two independent controls, matching the two ways access can be withdrawn:

**App-level — fast and graceful.** The `public_access_enabled` flag, toggled by
an admin via `POST /api/admin/toggle-public-access`. A public-channel request
while it is off receives a clean `503` explaining why. The intranet channel is
never affected — the two are deliberately independent. Takes effect within a few
seconds (an in-process cache, to avoid a database round trip per request).

**Host-level — the real kill switch.** `sudo ./scripts/toggle_public_access.sh off`
(also `on` / `status`), run directly on the host. It works even if the
application is completely wedged, because it does not depend on the application
at all: it inserts an `iptables` rule dropping inbound traffic to the public
listener's port, leaving the intranet listener untouched. If your host uses
`nft`, `ufw` or `firewalld` instead, adapt the single rule inside the script — it
exits with a clear message rather than silently doing nothing if `iptables` is
absent.

> **The public listener has not been verified end to end.** It stays commented
> out in `docker-compose.yml`, and no real public certificate or real inbound
> public traffic has been exercised against it. Treat it as a strong starting
> point, not a tested deployment target. See [TESTING.md](TESTING.md#what-was-not-tested).

---

## Deployment environment variables

These are in addition to everything in [CONFIGURATION.md](CONFIGURATION.md).

| Variable | Default | Purpose |
|---|---|---|
| `QC_AGENT_DATABASE_URL` | *unset* | Postgres connection string. **Setting this is what switches the app into multi-user mode.** |
| `QC_AGENT_JWT_SECRET` | *required once the above is set* | Signs session cookies; at least 32 bytes. The app fails fast at startup if missing while auth is active. |
| `QC_AGENT_REDIS_URL` | *unset* | Backs one-session-per-user enforcement and the rate limiter. Required alongside the database URL. |
| `QC_AGENT_LOGIN_RATE_LIMIT_MAX_ATTEMPTS` / `_WINDOW_SECONDS` | `10` / `60` | Per-IP login attempts per window before a 429. A backoff, not a lockout — there is no password-reset flow, so a lockout would strand a legitimate user. Keyed on nginx's `X-Real-IP`, so meaningful only behind nginx. |
| `QC_AGENT_REGISTER_RATE_LIMIT_MAX_ATTEMPTS` / `_WINDOW_SECONDS` | `10` / `60` | Same mechanism, separate budget, for registration. |
| `QC_AGENT_SESSION_TTL_SECONDS` | `604800` (7 days) | Session cookie lifetime. |
| `QC_AGENT_ADMIN_STORAGE_CACHE_TTL_SECONDS` | `20` | How long the admin storage readout is cached. Explicitly invalidated on every purge and config change, so a deliberate admin action is never masked by a stale value. |
| `QC_AGENT_DATABASE_POOL_MAX_SIZE` | `20` | Checkpointer connection pool size. Bounds concurrent checkpoint reads/writes, not concurrent chat turns. |
| `QC_AGENT_SERVER_HOST` / `QC_AGENT_SERVER_PORT` | `127.0.0.1` / `8000` | Overridden to `0.0.0.0` inside the container — nginx, not this process, is what faces the network. |
| `QC_AGENT_INTRANET_BIND` | *set in `.env`* | The host's LAN IP, used only by the compose port mapping for the intranet listener. |
| `QC_AGENT_LLM_GPU_IDS` | `0` | Which GPU indices vLLM may claim. Never defaults to "all available". |
| `QC_AGENT_VLLM_GPU_MEM_UTIL` | `0.65` | Fraction of VRAM vLLM pre-allocates for its runtime — deliberately below vLLM's own `0.9` default, for a shared host. |

---

## What is and is not finished

| Piece | Status |
|---|---|
| Compose stack, cookie-based JWT auth, per-IP rate limiting | Implemented and live-tested against real Postgres/Redis and a real browser |
| Per-user job/thread/KB ownership and isolation | Implemented and live-tested with two real accounts |
| Admin backend routes | Implemented and live-tested via the API |
| Storage quotas, concurrency caps, bulk purges, append-only audit log | Implemented and live-tested, including a real Postgres-trigger immutability test |
| Admin console UI | Implemented and browser-tested. User/invite management and the bug-report inbox are **not** in it yet |
| First-admin bootstrap and lockout recovery | Implemented and live-tested, including the all-admins-locked-out path |
| Intranet nginx listener | Implemented and live-tested end to end |
| **Public nginx listener** | **Not verified end to end.** Commented out by default |
| Host-level kill switch | Implemented for `iptables`; not yet run against a real firewall |
| vLLM inference backend | Present but commented out. Switching to it needs real tool-calling verification first |
| HPC / Slurm execution backend | Design-only, not built |

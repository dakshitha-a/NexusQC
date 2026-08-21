# Deployment guide

Running NexusQC as a multi-user service, with real accounts, per-user data
isolation, an admin console, and HTTPS.

If you just want NexusQC on your own machine, skip all of this — see the
Quickstart in the [README](../README.md). Single-user mode has no login and
no database at all.

**The switch between the two modes is one environment variable.** Setting
`QC_AGENT_DATABASE_URL` activates the whole auth layer: without it, none of
the auth or admin routes are even mounted, and the checkpointer stays on
SQLite.

---

## Before you start

You'll need:

| Requirement | Check it with | Notes |
|---|---|---|
| Docker Engine + Compose v2 | `docker compose version` | Compose v2 syntax (`docker compose`, not `docker-compose`) |
| A hostname or LAN IP to serve on | `ip -4 addr show \| grep inet` | Used for the intranet listener |
| A TLS certificate | — | Mandatory — login silently fails over plain HTTP, see below |
| ORCA and/or BAGEL *(optional)* | — | Never bundled; bind-mounted from the host |
| NVIDIA Container Toolkit *(optional)* | `docker info \| grep -i nvidia` | Only needed for the optional vLLM backend |

Pinned service versions, all set in `docker-compose.yml`: Postgres 16,
Redis 7, nginx 1.27, `python:3.11-slim-bookworm` for the API image.

> The Debian pin is deliberate, not an oversight. The unpinned
> `python:3.11-slim` tag drifted to Debian 13, whose repositories carry
> only OpenMPI 5.x — which dropped the C++ bindings library BAGEL links
> against, with no compatibility package available. Debian 12's OpenMPI
> 4.1.x still has it. Don't "modernise" this pin without testing a real
> BAGEL job first.

---

## Quick install (recommended)

```bash
git clone https://github.com/dakshitha-a/NexusQC.git
cd NexusQC
scripts/install.sh
```

One interactive script covers everything in steps 1–8 below: it generates
`.env` with fresh secrets, asks whether to publish on your LAN and/or
Tailscale (localhost always works), generates the self-signed intranet
certificate, detects ORCA/BAGEL on the host (or lets you skip either — you
get a PySCF-only deployment, and can re-run the installer later once they're
installed), checks that Ollama is reachable, builds and starts the stack, and
creates the first admin account. It ends with a running, reachable
deployment.

Read on if you'd rather do each step by hand, want to understand what the
installer is actually doing, or need to adapt one of these steps for your
environment.

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

Now edit `.env`. Three values need to change before anything will start:

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
- `QC_AGENT_LAN_BIND` — the LAN IP you just found (e.g. `192.168.1.50`)
- `QC_AGENT_TAILSCALE_BIND` — this host's tailnet IP, if it has one. Both
  variables are required for `docker compose up` to even parse
  `docker-compose.yml`; if you don't want one of them actually published,
  set it to `127.0.0.1` and replace `docker-compose.yml`'s `ports:` list for
  the `nginx` service with your own in `docker-compose.override.yml` (see
  `docker-compose.dev.yml`'s `ports: !override` for the pattern) rather than
  leaving an address bound you didn't intend to expose.

Also set the file-ownership variables, so the container writes into
`./data` as **you** instead of as root. Skip this and job artifacts and
uploads end up owned by a uid you can't delete without `sudo`:

```bash
echo "APP_UID=$(id -u)" >> .env
echo "APP_GID=$(id -g)" >> .env
```

## 3. Provide a TLS certificate

Both nginx listeners have to use HTTPS. The session cookie is marked
`Secure`, so over plain HTTP login just appears to do nothing at all — no
error, just a form that never proceeds. This is the single most common
first-deployment failure people hit.

Nothing generates the certificate for you; `nginx/nginx.conf` expects the
files to already exist.

For an intranet deployment, a self-signed certificate is fine:

```bash
mkdir -p nginx/certs
openssl req -x509 -nodes -days 825 -newkey rsa:2048 \
  -keyout nginx/certs/intranet.key \
  -out nginx/certs/intranet.crt \
  -subj "/CN=$(hostname -f)" \
  -addext "subjectAltName=DNS:$(hostname -f),IP:<YOUR_LAN_IP>"
```

Replace `<YOUR_LAN_IP>` with the address you put in `.env`. Browsers will
complain about the self-signed certificate — that's expected on an
intranet, not a sign something's wrong.

For a public listener, use a real certificate from a certificate authority
(certbot / Let's Encrypt). Provisioning that is outside what this repo
covers.

`nginx/nginx.conf` parses **both** server blocks unconditionally, so nginx
refuses to start without `nginx/certs/public.crt`/`public.key` even while
that listener's port stays commented out in `docker-compose.yml` and is
never actually reachable. A placeholder self-signed certificate is enough
to satisfy this — `scripts/install.sh` generates one automatically — but
replace it with a real one before ever uncommenting the public listener's
port:

```bash
openssl req -x509 -newkey rsa:2048 -noenc -days 825 \
  -keyout nginx/certs/public.key -out nginx/certs/public.crt \
  -subj "/CN=$(hostname -f)"
```

## 4. Enable ORCA / BAGEL (optional)

Skip this if you only need PySCF, which ships inside the image and covers
most calculation types on its own.

ORCA and BAGEL are never bundled into any image. ORCA's licence explicitly
forbids redistribution, and both engines get treated the same way
regardless — they're bind-mounted read-only from wherever they already
live on your host.

```bash
cp docker-compose.override.yml.example docker-compose.override.yml
```

Edit that file so both the `volumes:` paths and the matching
`QC_AGENT_*_BIN` environment variables point at your real installs. Use
the same absolute path on both sides of each mount, so one value works for
both the container and any bare-metal run.

BAGEL additionally needs its Intel oneAPI environment.
`docker/entrypoint.sh` sources it automatically if the oneAPI directory is
mounted, and skips it harmlessly (with a log line) if you're not using
BAGEL.

## 5. Build and start

```bash
docker compose build
docker compose up -d postgres redis
```

Give Postgres a few seconds to accept connections, then bring up the rest:

```bash
docker compose up -d
```

Check it came up:

```bash
docker compose ps          # every service should be "running"
docker compose logs -f api # should end with uvicorn listening on 0.0.0.0:8000
```

## 6. Build the frontend

Easy to miss, and it produces a confusing result if you do.

nginx serves `frontend/dist` from a host bind mount, completely
independent of whatever frontend build sits inside the API image.
`docker compose build` does not refresh it. Skip this step and the
deployed UI stays an old build even though everything else came up clean.

```bash
conda activate node24   # or any Node >= 24.14.1
cd frontend && npm ci && npm run build && cd ..
```

Node 24 isn't optional here — it's what Ketcher, the 2D structure editor,
declares in its `engines` field.

## 7. Create the first admin account

This is deliberately a filesystem-local command rather than a web form.
The whole point is that it requires shell access to the host, not a web
credential:

```bash
docker compose run --rm api python -m server.admin_cli bootstrap-admin \
  --email you@yourlab.edu --username admin
```

It prompts for a password and prints a confirmation. It refuses to run if
an admin account already exists.

## 8. Log in

Open `https://<your-LAN-IP>:8443` and sign in with the account you just
created. Accept the self-signed certificate warning.

New users join by invite token, generated by an admin. There's no open
registration.

---

## Upgrading a deployment that previously ran as root

Everything already under `data/` is root-owned, and the non-root container
can't write to it — so the first molecule lookup or job submission fails
with `PermissionError`. Fix it once, before `docker compose up`:

```bash
docker run --rm -v "$PWD/data:/d" alpine chown -R "$(id -u):$(id -g)" /d
```

---

## Running a development stack alongside this one

If people other than you depend on this deployment, don't test changes in
it. Stand up a second, destructible stack from a separate checkout of the
same repository and put every change through that first.
[WORKFLOW.md](WORKFLOW.md) covers the ongoing procedure; this is the
one-time setup.

Mark each checkout for what it is. This file is untracked, holds one word,
and is what stops `dev_stack.sh reset` from destroying the wrong database:

```bash
echo production > /path/to/production-checkout/.deployment-role
echo dev        > /path/to/dev-checkout/.deployment-role
```

Then give each stack its own `.env`. Four values have to differ, and each
one is a different kind of trouble if it doesn't:

| Value | Production | Development | If shared |
|---|---|---|---|
| `COMPOSE_PROJECT_NAME` | e.g. `nexusqc_prod` | e.g. `nexusqc_dev` | one Postgres volume, one database, shared accounts and chat history |
| `QC_AGENT_POSTGRES_PASSWORD` | its own | its own | either stack can reach the other's database |
| `QC_AGENT_JWT_SECRET` | its own | its own | a dev session cookie is valid against production |
| listener | LAN + tailnet, `8443` | loopback + tailnet, `QC_AGENT_DEV_PORT` (8444) | users find the dev stack and file bugs against it |

Generate the dev secrets the same way as in step 2 above. Don't copy
production's `.env` across — that's exactly the mistake `dev_stack.sh`
checks for on every run.

Point the dev checkout at production so those checks can actually run, by
adding to the **dev** `.env`:

```bash
QC_AGENT_PROD_DIR=/path/to/production-checkout
QC_AGENT_DEV_PORT=8444
```

The production checkout stays never-edited-by-hand and never-on-a-branch —
it sits on a detached HEAD at the deployed commit, so `git status` there
answers "what is the lab running" truthfully. Move it only with:

```bash
scripts/promote.sh --dry-run     # every gate and the full impact report
scripts/promote.sh --drain       # wait for running jobs, then promote
```

Both stacks share this host's Ollama and the same job-admission gate, so
keep dev on the same model as production and leave its job caps small.
`docker-compose.dev.yml` explains what goes wrong if you don't, and the
failure mode is a quiet one.

---

## Day-to-day administration

Most administration happens in the React admin console, reachable from the
account bar in the top-right corner once you're logged in as an admin. It
covers storage quotas, the live usage readout, concurrency caps, bulk
purges, the audit log, and the public-access toggle.

Two things the console doesn't cover yet — user and invite-token
management, and the bug-report inbox — go through the API directly. These
examples assume a cookie jar saved from logging in first:

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

Recover with the filesystem-local CLI. This needs shell access to the
host by design — it exists for exactly the case where no web
authentication path works:

```bash
# Clears users, sessions and invite tokens. Job/thread/KB data under ./data
# is preserved unless you add --wipe-data. The audit log and bug reports
# survive with their user references nulled.
docker compose run --rm api python -m server.admin_cli reset-all --confirm

# Then bootstrap a fresh admin, as in step 7.
```

---

## Storage quotas

Storage is capped and self-evicting, oldest-first, across four categories:

| Category | Default | Scope |
|---|---|---|
| Knowledge-base uploads | 2 GB | Per user |
| Geometry/blind-input uploads | 500 MB | Per user |
| Job artifacts **and** chat history | 18 GB | Per user, one shared pool |
| Everything, all users combined | 200 GB | Global — a single cap, not per-category |

Concurrency is capped separately, and it's also editable at runtime from
the console or `PATCH /api/admin/config`:

| Limit | Default | Notes |
|---|---|---|
| Concurrent jobs, all users | 20 | Clamped to `QC_AGENT_MAX_CONCURRENT_JOBS`, which fixes the worker-pool size at process start and can't be resized live |
| Concurrent jobs, per user | 5 | Stops one user monopolising the queue |
| Cores per job | 4 | `QC_AGENT_N_CORES`. Per-job width, not a total — 20 × 4 is up to 80 cores in flight |

NexusQC doesn't reserve a fixed slice of the machine for itself — every
core is available, and the host-load admission gate is what actually
prevents oversubscription. Raise `QC_AGENT_N_CORES` for wide single jobs,
lower it to favour many small ones, but see the warning in
[CONFIGURATION.md](CONFIGURATION.md#job-execution-and-resource-limits)
about pushing it too close to your total core count.

Eviction runs oldest-first after every job submission and every
knowledge-base upload, plus every ~5 minutes from the background watcher
to catch chat-history growth, which has no per-message hook of its own. A
pending or running job, and the pre-seeded manual corpus, are never
evicted.

Every quota change and every purge — automatic or manual — is written to
an audit log that's genuinely append-only: a Postgres trigger rejects
`UPDATE`, `DELETE` and `TRUNCATE` outright, rather than just relying on
there being no route that exposes one.

---

## Intranet and public access

Two independent controls, matching the two ways access can actually get
withdrawn.

**App-level, fast and graceful.** The `public_access_enabled` flag,
toggled by an admin via `POST /api/admin/toggle-public-access`. A
public-channel request while it's off gets a clean `503` explaining why.
The intranet channel is never affected — the two are deliberately
independent of each other. Takes effect within a few seconds (an
in-process cache, to avoid a database round trip on every request).

**Host-level, the real kill switch.**
`sudo ./scripts/toggle_public_access.sh off` (also `on` / `status`), run
directly on the host. It works even if the application is completely
wedged, because it doesn't depend on the application at all — it inserts
an `iptables` rule dropping inbound traffic to the public listener's port,
leaving the intranet listener untouched. Running `nft`, `ufw` or
`firewalld` instead? Adapt the one rule inside the script; it exits with a
clear message rather than silently doing nothing if `iptables` isn't
there.

> The public listener has not been verified end to end. It stays
> commented out in `docker-compose.yml`, and no real public certificate or
> real inbound public traffic has been exercised against it yet. Treat it
> as a strong starting point, not a tested deployment target. See
> [TESTING.md](TESTING.md#what-was-not-tested).

---

## Backup, restore, and updating

**Backup** (`scripts/backup.sh`) dumps the whole Postgres database — every
account, session, ownership record, the append-only audit log, and (once
`QC_AGENT_DATABASE_URL` is set) every conversation's full chat history — plus
`.env`, `docker-compose.override.yml`, TLS certs, and `data/threads.json`.
Job artifacts (`data/jobs`) and the knowledge base (`data/kb`) are excluded by
default: they're bulk data, and `data/kb` is reproducible from `data/scraped`
via `scripts/seed_knowledge_base.py`. Pass `--full` to also archive those —
worth doing before an update, since there's no separate stack to fall back to
if something in `data/` goes wrong:

```bash
scripts/backup.sh              # database + config/secrets (fast, default)
scripts/backup.sh --full       # + data/jobs, data/kb, data/uploads, etc.
scripts/backup.sh --list       # show what's currently retained
```

Point `QC_AGENT_BACKUP_DIR` at a filesystem with real room (not wherever
`/var/lib/docker` sits), and install it as a user crontab for nightly
coverage:

```cron
0 3 * * * cd /path/to/NexusQC && ./scripts/backup.sh >> backups/backup.log 2>&1
```

**Restore** (`scripts/restore.sh <backup-directory>`) reverses that: it stops
the `api` container, restores the database, and restarts it. It does **not**
touch `.env` or certificates — overwriting live secrets from an old backup is
not something a restore should do unprompted. If the chosen backup was taken
with `--full`, it separately offers (with its own confirmation) to also
restore `data/` from the archive.

**Updating** to a newer commit is `scripts/update.sh`, the counterpart to
`scripts/install.sh` for a deployment that isn't the maintainers' own
dev/production pair (see `docs/WORKFLOW.md` — those use `scripts/promote.sh`
instead, gated on a separate verified dev stack). `scripts/update.sh`:

```bash
scripts/update.sh              # fetch and update to origin/main
scripts/update.sh --dry-run    # report what would happen, change nothing
scripts/update.sh --drain      # wait for in-flight jobs before restarting
scripts/update.sh --force      # accept killing in-flight jobs
scripts/update.sh --rollback   # go back to the commit before the last update
```

It reports what the change would do to the running deployment before
touching anything (schema changes that would be silent no-ops, new required
`.env` variables, engine mounts that would quietly disappear), refuses to
proceed past anything destructive without an explicit decision, takes a full
backup unconditionally, and — if the update would restart the containers —
asks how to handle any job currently running rather than guessing. A
rollback only undoes the code: a schema change stays, since the pre-update
backup is the only real way back from one.

---

## Deployment environment variables

These are in addition to everything in
[CONFIGURATION.md](CONFIGURATION.md).

| Variable | Default | Purpose |
|---|---|---|
| `QC_AGENT_DATABASE_URL` | *unset* | Postgres connection string. Setting this is what switches the app into multi-user mode. |
| `QC_AGENT_JWT_SECRET` | *required once the above is set* | Signs session cookies; at least 32 bytes. The app fails fast at startup if it's missing while auth is active. |
| `QC_AGENT_REDIS_URL` | *unset* | Backs one-session-per-user enforcement and the rate limiter. Required alongside the database URL. |
| `QC_AGENT_LOGIN_RATE_LIMIT_MAX_ATTEMPTS` / `_WINDOW_SECONDS` | `10` / `60` | Per-IP login attempts per window before a 429. A backoff, not a lockout — there's no password-reset flow, so a lockout would strand a legitimate user. Keyed on nginx's `X-Real-IP`, so it only means anything behind nginx. |
| `QC_AGENT_REGISTER_RATE_LIMIT_MAX_ATTEMPTS` / `_WINDOW_SECONDS` | `10` / `60` | Same mechanism, separate budget, for registration. |
| `QC_AGENT_SESSION_TTL_SECONDS` | `604800` (7 days) | Session cookie lifetime. |
| `QC_AGENT_ADMIN_STORAGE_CACHE_TTL_SECONDS` | `20` | How long the admin storage readout is cached. Explicitly invalidated on every purge and config change, so a deliberate admin action never sits behind a stale value. |
| `QC_AGENT_DATABASE_POOL_MAX_SIZE` | `20` | Checkpointer connection pool size. Bounds concurrent checkpoint reads/writes, not concurrent chat turns. |
| `QC_AGENT_SERVER_HOST` / `QC_AGENT_SERVER_PORT` | `127.0.0.1` / `8000` | Overridden to `0.0.0.0` inside the container — nginx, not this process, is what actually faces the network. |
| `QC_AGENT_LAN_BIND` | *set in `.env`* | The host's LAN IP, used only by the compose port mapping for the intranet listener. |
| `QC_AGENT_TAILSCALE_BIND` | *set in `.env`* | The host's tailnet IP, same mapping. Both this and `QC_AGENT_LAN_BIND` must be set for `docker compose up` to parse `docker-compose.yml` at all, even if `docker-compose.override.yml`'s `ports: !override` replaces the actual published list — `scripts/install.sh` handles this automatically. |
| `QC_AGENT_BACKUP_DIR` / `QC_AGENT_BACKUP_RETAIN_DAYS` | `./backups` / `30` | Where `scripts/backup.sh` writes, and how long it keeps old backups. |
| `QC_AGENT_LLM_GPU_IDS` | `0` | Which GPU indices vLLM may claim. Never defaults to "all available." |
| `QC_AGENT_VLLM_GPU_MEM_UTIL` | `0.65` | Fraction of VRAM vLLM pre-allocates for its runtime, deliberately below vLLM's own `0.9` default, for a shared host. |

---

## What is and is not finished

| Piece | Status |
|---|---|
| Compose stack, cookie-based JWT auth, per-IP rate limiting | Implemented and live-tested against real Postgres/Redis and a real browser |
| Per-user job/thread/KB ownership and isolation | Implemented and live-tested with two real accounts |
| Admin backend routes | Implemented and live-tested via the API |
| Storage quotas, concurrency caps, bulk purges, append-only audit log | Implemented and live-tested, including a real Postgres-trigger immutability test |
| Admin console UI | Implemented and browser-tested. User/invite management and the bug-report inbox aren't in it yet |
| First-admin bootstrap and lockout recovery | Implemented and live-tested, including the all-admins-locked-out path |
| Interactive installer (`scripts/install.sh`), full backup/restore, standalone updater (`scripts/update.sh`) | Implemented and run end to end against a scratch deployment |
| Intranet nginx listener | Implemented and live-tested end to end |
| Public nginx listener | Not verified end to end. Commented out by default |
| Host-level kill switch | Implemented for `iptables`; not yet run against a real firewall |
| vLLM inference backend | Present but commented out. Switching to it needs real tool-calling verification first |
| HPC / Slurm execution backend | Design-only, not built |

# Deployment guide

Running NexusQC as a multi-user service, with real accounts, per-user data
isolation, an admin console, and HTTPS.

`scripts/install.sh` covers everything here interactively and is the
recommended path. See [Quick install](#quick-install-recommended) below. The
step-by-step sections after it exist for when you want to do a step by hand or
adapt one to your environment.

If you're working on NexusQC rather than deploying it, the bare
`server.main` + Vite loop is in
[DEVELOPMENT.md](DEVELOPMENT.md#running-from-source). That mode has no login
and no database at all.

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
| A TLS certificate | - | Mandatory, login silently fails over plain HTTP, see below |
| ORCA and/or BAGEL *(optional)* | - | Never bundled; bind-mounted from the host |
| NVIDIA Container Toolkit *(optional)* | `docker info \| grep -i nvidia` | Only needed for the vLLM backend, which has never been exercised |
| A GPU with **24 GB of VRAM**, or patience | `nvidia-smi` | See below. Not a hard requirement; it is what makes the app pleasant rather than possible |

### How much GPU you need, and what happens if you have less

The served chat model is the app's real hardware requirement, not the quantum
chemistry: PySCF, ORCA and BAGEL are CPU work. The default `qwen3.8:27b` sits
at **16.3 GB resident in VRAM** while serving, and with headroom for the
context window and the embedding model beside it, **24 GB is the practical
floor**. That is a single consumer card -- an RTX 3090, 4090 or 5090 -- as much
as a workstation or datacentre GPU. With less VRAM it will run on CPU and
system RAM, considerably slower.

Reaching for a smaller model to fit a smaller card is the obvious move and it
does not go well. Measured over 108 scored trials on one task set:

| Model | End-to-end tasks | Elicitation | Grounding |
|---|---|---|---|
| `qwen3.8:27b` (16.3 GB) | 55/60 | 31/36 | 30/30 |
| 14B (8.6 GB) | 14/30 | 6/18 | 12/12 |
| 8B (4.9 GB) | 0/29 | 0/18 | 1/1 |

The 8B row is the one to read twice: it is not "worse answers", it is an agent
that cannot reliably emit a tool call, and an agent that cannot call tools
cannot run a calculation at all. Grounding holds across all three because
reported numbers are read from files on disk rather than produced by the
model -- which is a property of the design, not of the model, and is exactly
why it is the thing that survives.

### What this deployment is for, and where it stops

This is built for a **lab or small-group deployment**: one machine, one GPU,
a handful of people who mostly are not typing at the same instant. Ollama
serves that well and asks almost nothing of whoever sets it up -- one pull,
one environment variable, and better hardware makes it faster with no
configuration change at all, because Ollama sizes its own concurrency from
available VRAM.

**Where it stops is concurrency, and the reason is measured rather than
assumed.** Each simultaneous conversation needs its own key/value cache, and
Ollama reserves a full context window per slot. At this model's shape a
64k-token context is roughly 17 GB of cache, so a 32 GB card holds one slot
alongside 16 GB of weights. Four people talking at once therefore queue:
first-output times of 2.5, 7.8, 10.4 and 13.7 seconds in a real measurement
(`tests/backend/perf_02_ttft_and_concurrency.py`), against 1.9 s for one
person alone. Nothing is broken -- it is a queue, and for a handful of users
who take turns thinking it is barely noticeable -- but it does not scale by
adding users.

**For an HPC or shared-cluster deployment, the answer is a paged-KV
inference server, and vLLM is the one this repository is already shaped
for.** Paged attention allocates cache in blocks as sequences actually grow,
instead of reserving a whole context per slot, so users who are rarely all
at maximum context pack into memory that Ollama must set aside up front. It
also brings continuous batching, and automatic prefix caching over the
system prompt and tool schema -- which are byte-identical on every turn and
across every user here, so that last one is worth more to this app than to
most.

A commented-out `vllm` service in `docker-compose.yml` carries a working
starting configuration: a deliberately low GPU-memory fraction for a shared
host, a GPU-id allowlist so the app never claims every card, and the
tool-call and reasoning parser flags. **It has never been exercised, and is
not part of this deployment.** Two things would have to be settled before it
is: vLLM serves safetensors rather than Ollama's GGUF, so it runs a
different quantisation of the same model and the agent's tool-calling
behaviour has to be re-measured (`tests/backend/model_compat.py` is that
check); and the tool-call parser must match the model family exactly,
because the failure mode when it does not is tool calls silently vanishing,
which in this app means nothing runs.

Pinned service versions, all set in `docker-compose.yml`: Postgres 16,
Redis 7, nginx 1.27, `python:3.11-slim-bookworm` for the API image.

> The Debian pin is deliberate, not an oversight. The unpinned
> `python:3.11-slim` tag drifted to Debian 13, whose repositories carry
> only OpenMPI 5.x, which dropped the C++ bindings library BAGEL links
> against, with no compatibility package available. Debian 12's OpenMPI
> 4.1.x still has it. Don't "modernise" this pin without testing a real
> BAGEL job first.

---

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
certificate, detects ORCA/BAGEL on the host (or lets you skip either, you
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

- `QC_AGENT_POSTGRES_PASSWORD`, the first generated value
- `QC_AGENT_JWT_SECRET`, the second generated value
- `QC_AGENT_LAN_BIND`, the LAN IP you just found (e.g. `192.168.1.50`)
- `QC_AGENT_TAILSCALE_BIND`. This host's tailnet IP, if it has one. Both
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
`Secure`, so over plain HTTP login just appears to do nothing at all, no
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
complain about the self-signed certificate, that's expected on an
intranet, not a sign something's wrong.

Only one certificate is needed. `nginx/nginx.conf` used to parse a second,
public server block unconditionally, so nginx refused to start without a
`public.crt`/`public.key` pair that nothing ever served -- that block was
removed on 2026-08-25 and the placeholder certificate with it.

## 4. Enable ORCA / BAGEL (optional)

Skip this if you only need PySCF, which ships inside the image and covers
most calculation types on its own.

ORCA and BAGEL are never bundled into any image. ORCA's licence explicitly
forbids redistribution, and both engines get treated the same way
regardless. They're bind-mounted read-only from wherever they already
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

Node 24 isn't optional here. It's what Ketcher, the 2D structure editor,
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
can't write to it, so the first molecule lookup or job submission fails
with `PermissionError`. Fix it once, before `docker compose up`:

```bash
docker run --rm -v "$PWD/data:/d" alpine chown -R "$(id -u):$(id -g)" /d
```

---

## Day-to-day administration

Most administration happens in the React admin console, reachable from the
account bar in the top-right corner once you're logged in as an admin. It
covers storage quotas, the live usage readout, concurrency caps, bulk
purges and the audit log.

Two things the console doesn't cover yet, user and invite-token
management, and the bug-report inbox, go through the API directly. These
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
host by design. It exists for exactly the case where no web
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
| Everything, all users combined | 200 GB | Global. A single cap, not per-category |

Concurrency is capped separately, and it's also editable at runtime from
the console or `PATCH /api/admin/config`:

| Limit | Default | Notes |
|---|---|---|
| Concurrent jobs, all users | 20 | Clamped to `QC_AGENT_MAX_CONCURRENT_JOBS`, which fixes the worker-pool size at process start and can't be resized live |
| Concurrent jobs, per user | 5 | Stops one user monopolising the queue |
| Cores per job | 4 | `QC_AGENT_N_CORES`. Per-job width, not a total, 20 × 4 is up to 80 cores in flight |

NexusQC doesn't reserve a fixed slice of the machine for itself. Every
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

Every quota change and every purge, automatic or manual. Is written to
an audit log that's genuinely append-only: a Postgres trigger rejects
`UPDATE`, `DELETE` and `TRUNCATE` outright, rather than just relying on
there being no route that exposes one.

---

## How this deployment is reached

Two ways in, both private, and no third.

**The intranet listener**, on the LAN address you set as
`QC_AGENT_LAN_BIND`, and **a tailnet address** via `QC_AGENT_TAILSCALE_BIND`.
Loopback is published as well so `curl` on the host works. That is the whole
surface.

**There is no public-internet listener.** There was a second nginx server
block for one, and it was never reachable: its port had been commented out of
`docker-compose.yml` since before anyone tried to use it. Around that unused
door had grown a set of locks -- an admin-panel toggle, a middleware check
keyed on an `X-Access-Channel` header, a host firewall script -- all of them
guarding something that was not in the wall. On 2026-08-25 the listener and
every one of those controls were removed together.

The practical consequences are all simplifications: one certificate instead
of two, no `sudo` firewall step to rehearse, one fewer admin control that
could be clicked in an emergency and quietly do nothing, and no public
attack surface to reason about.

**To serve publicly**, restore the listener deliberately -- git history has
the original block. It needs its port published, a real certificate from a
certificate authority (certbot / Let's Encrypt; provisioning that is outside
what this repo covers), and a fresh decision about how access is withdrawn,
because the mechanisms that used to do it are gone. On a managed network,
talk to whoever runs the firewall before any of that: an announced test is
routine, and the same traffic unannounced is an incident.

---

## What is not built for, and what it would take

Three things this deployment has never done. None is a defect; all three are
scope, and writing down what each would actually require is more useful than
carrying them as an open question.

### More than one host

Everything assumes one machine. `JobManager` schedules against *this* host's
CPU and memory headroom, jobs write into a local `data/` bind mount, and the
SSE hub is an in-process `queue.Queue` shared by threads inside one API
process (see `server/sse.py`). Splitting across hosts means all three change:
a scheduler that knows about a cluster, shared or replicated job storage, and
an SSE fan-out that survives a request landing on a different replica -- Redis
is already a dependency and is the obvious place for the last one. Until then,
scale vertically. The machine this was built on has 255 cores and 1 TB of RAM,
which is a long runway.

### A certificate authority's certificate

The install generates a self-signed certificate for the intranet listener,
and browsers warn about it. That is expected on a LAN and is not a sign
anything is wrong. A real certificate (certbot / Let's Encrypt, or your
institution's own CA) needs a resolvable hostname and, for automated renewal,
a challenge path -- neither of which this repo sets up. Nothing in the app
cares which certificate nginx serves; it is an nginx and DNS question.

### More than a handful of people at once

Measured, not assumed: four simultaneous conversations on one GPU queue
behind each other, at 2.5, 7.8, 10.4 and 13.7 seconds to first output against
1.9 s for one person alone (`tests/backend/perf_02_ttft_and_concurrency.py`).
The cause is that each concurrent slot reserves a full context window of
key/value cache -- about 17 GB at this model's shape -- so one 32 GB card
holds one slot beside 16 GB of weights.

For a handful of people who take turns thinking, that queue is barely
noticeable. Beyond that the levers are, in increasing order of effort: a
shorter served context (`OLLAMA_NUM_PARALLEL` will then choose more slots), a
larger GPU, or an inference server that pages the KV cache rather than
reserving it -- see "What this deployment is for, and where it stops" above.
Load beyond one operator has never been tested, and the number to watch when
someone does is time to first output, not throughput: that is what a waiting
person actually experiences.

---

## Backup, restore, and updating

**Backup** (`scripts/backup.sh`) dumps the whole Postgres database, every
account, session, ownership record, the append-only audit log, and (once
`QC_AGENT_DATABASE_URL` is set) every conversation's full chat history, plus
`.env`, `docker-compose.override.yml`, TLS certs, and `data/threads.json`.
Job artifacts (`data/jobs`) and the knowledge base (`data/kb`) are excluded by
default: they're bulk data, and `data/kb` is reproducible from `data/scraped`
via `scripts/seed_knowledge_base.py`. Pass `--full` to also archive those.
Worth doing before an update, since there's no separate stack to fall back to
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
touch `.env` or certificates. Overwriting live secrets from an old backup is
not something a restore should do unprompted. If the chosen backup was taken
with `--full`, it separately offers (with its own confirmation) to also
restore `data/` from the archive.

**Updating** to a newer commit is `scripts/update.sh`, the counterpart to
`scripts/install.sh`. This is the one way any deployment moves forward,
whether it's your own or someone else's:

```bash
scripts/update.sh              # fetch and update to origin/main
scripts/update.sh --dry-run    # report what would happen, change nothing
scripts/update.sh --drain      # wait for in-flight jobs before restarting
scripts/update.sh --force      # accept killing in-flight jobs
scripts/update.sh --rollback   # go back to the last commit that came up healthy
```

It reports what the change would do to the running deployment before
touching anything (schema changes that would be silent no-ops, new required
`.env` variables, engine mounts that would quietly disappear), refuses to
proceed past anything destructive without an explicit decision, takes a full
backup unconditionally, and, if the update would restart the containers.
Asks how to handle any job currently running rather than guessing. A
rollback only undoes the code: a schema change stays, since the pre-update
backup is the only real way back from one.

**Dependency changes are reported package by package.** When
`requirements.txt` moves, the report does not merely say that it moved: it
prints the transitions, so you can see before agreeing whether the rebuild
reinstalls the same versions or pulls in something new.

```
dependency changes:
  ~ pyscf  unpinned -> ==2.14.0
  + some-package  (new, UNPINNED -- resolves to whatever is latest at build time)
  - dropped-package  (removed)
```

A change that touches only comments says so rather than leaving you to
guess. An ADDED package also carries a warning that it may need a system
package the `Dockerfile` does not install, because that is how this bites:
a source-only distribution needing a compiler, BLAS or headers fails during
`pip install`, minutes into the build. That failure is safe by design, since
the image is built before the running stack is stopped, and the fix is an
apt line in the `Dockerfile` rather than a rollback. It happened once, with
an unpinned `pyscf-forge` that resolved to a version with no wheel, which is
why both it and `pyscf` are now pinned.

**What "currently running" means.** The script asks the deployment, not the
checkout. The api image carries the commit it was built from as an OCI
revision label, and the built frontend bundle carries the same in
`frontend/dist/.build-commit`. Those two are what is actually serving
traffic, and on a deployment where the checkout and the stack are the same
directory, either can sit behind `HEAD` for as long as nobody rebuilds.
Asking `HEAD` instead used to make the script report "already up to date"
whenever a commit had been made but not deployed, which is precisely when
somebody most needs it to work.

An image built by hand rather than by this script carries no usable stamp.
That reads as "cannot tell, so assume stale" and the update runs; it is never
read as up to date. Your first run against an existing deployment will
therefore rebuild once, whatever the checkout says, and report accurately
from then on. To stamp a hand-run build yourself:

```bash
QC_AGENT_BUILD_COMMIT=$(git rev-parse HEAD) docker compose up -d --build
```

When only the build is behind, the checkout is left where it is and nothing
is written to `.update-log`. An entry there would name the same commit as
both the new and the previous one, and `--rollback` reads that file to decide
where to go back to.

**What a failed update tells you to do.** `--rollback` moves code and nothing
else, so it is the right answer for exactly one situation: a change that the
impact report did not call destructive, on a deployment whose checkout
actually moved. After a destructive update it would leave the old code
running against an already-migrated database, so the script names the backup
directory and `scripts/restore.sh` instead. It used to suggest `--rollback`
in every case.

The health check finds the deployment by asking Compose which port it
publishes, rather than assuming the default, and tries every address Compose
names. Set `QC_AGENT_UPDATE_HEALTH_URL` to override that. This matters more
than it looks: a wrong answer here is not just a scary message any more, it
decides what `--rollback` will return to.

`.update-log` also records whether the deployment came up healthy, because
the health check is the difference between "this commit is where to go back
to" and "this commit is the problem". An update whose health check failed is
written with an `unhealthy` verb, and `--rollback` skips past it to the most
recent commit the deployment is known to have actually run. Previously the
`updated` line was appended before the health check was even considered, so a
deployment that never came up was recorded as the new baseline.

---

## Deployment environment variables

These are in addition to everything in
[CONFIGURATION.md](CONFIGURATION.md).

| Variable | Default | Purpose |
|---|---|---|
| `QC_AGENT_DATABASE_URL` | *unset* | Postgres connection string. Setting this is what switches the app into multi-user mode. |
| `QC_AGENT_JWT_SECRET` | *required once the above is set* | Signs session cookies; at least 32 bytes. The app fails fast at startup if it's missing while auth is active. |
| `QC_AGENT_REDIS_URL` | *unset* | Backs one-session-per-user enforcement and the rate limiter. Required alongside the database URL. |
| `QC_AGENT_LOGIN_RATE_LIMIT_MAX_ATTEMPTS` / `_WINDOW_SECONDS` | `10` / `60` | Per-IP login attempts per window before a 429. A backoff, not a lockout. There's no password-reset flow, so a lockout would strand a legitimate user. Keyed on nginx's `X-Real-IP`, so it only means anything behind nginx. |
| `QC_AGENT_REGISTER_RATE_LIMIT_MAX_ATTEMPTS` / `_WINDOW_SECONDS` | `10` / `60` | Same mechanism, separate budget, for registration. |
| `QC_AGENT_SESSION_TTL_SECONDS` | `604800` (7 days) | Session cookie lifetime. |
| `QC_AGENT_ADMIN_STORAGE_CACHE_TTL_SECONDS` | `20` | How long the admin storage readout is cached. Explicitly invalidated on every purge and config change, so a deliberate admin action never sits behind a stale value. |
| `QC_AGENT_DATABASE_POOL_MAX_SIZE` | `20` | Checkpointer connection pool size. Bounds concurrent checkpoint reads/writes, not concurrent chat turns. |
| `QC_AGENT_SERVER_HOST` / `QC_AGENT_SERVER_PORT` | `127.0.0.1` / `8000` | Overridden to `0.0.0.0` inside the container, nginx, not this process, is what actually faces the network. |
| `QC_AGENT_LAN_BIND` | *set in `.env`* | The host's LAN IP, used only by the compose port mapping for the intranet listener. |
| `QC_AGENT_TAILSCALE_BIND` | *set in `.env`* | The host's tailnet IP, same mapping. Both this and `QC_AGENT_LAN_BIND` must be set for `docker compose up` to parse `docker-compose.yml` at all, even if `docker-compose.override.yml`'s `ports: !override` replaces the actual published list, `scripts/install.sh` handles this automatically. |
| `QC_AGENT_BACKUP_DIR` / `QC_AGENT_BACKUP_RETAIN_DAYS` | `./backups` / `30` | Where `scripts/backup.sh` writes, and how long it keeps old backups. |
| `QC_AGENT_LLM_GPU_IDS` | `0` | Which GPU indices vLLM may claim. Never defaults to "all available." |
| `QC_AGENT_VLLM_GPU_MEM_UTIL` | `0.65` | Fraction of VRAM vLLM pre-allocates for its runtime, deliberately below vLLM's own `0.9` default, for a shared host. **Read only if the `vllm` service is uncommented, which it never has been:** no real turn has been served through vLLM, and Ollama is the supported backend. |

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

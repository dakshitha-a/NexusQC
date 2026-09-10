# Tracker: the installer, audited

**In motion, opened 2026-09-10.** Six phases. `scripts/install.sh` is the
entrypoint: for most people it is the only NexusQC code they will ever watch
run, and it had never been audited or tested. This makes it robust first and
presentable second.

It stays here rather than moving to [`trackers/`](trackers/) until the next
plan starts. **Exactly one tracker is active at a time.** The one this replaces
is
[`trackers/2026-09-job-row-width-and-stop-control.md`](trackers/2026-09-job-row-width-and-stop-control.md).

## Rules (enforced by `scripts/check_tracker.py`)

- Step status is exactly one of `todo` | `in-progress` | `done`.
- A step may be marked `done` **only with an evidence field**: the
  verification script/command path plus a one-line observed result.
- The tracker edit ships **in the same commit** as the step's final code
  change, so `git log --follow docs/TRACKER.md` is the audit trail.
- A phase's `merged` row records the commit hash the stage landed as, and it
  must be a bare hash; the checker rejects anything else.

Format for a step row:

```
- [status] P<phase>.<step>: <short name>
  evidence: <script/command> → "<observed result>"   (required when done)
```

---

## Why this plan exists

The installer was already carefully engineered in the places someone had
thought hard about: a POSIX prologue that survives dash, a deliberate refusal
to `git pull` a checkout out from under `update.sh`, a `< /dev/null` on the
psql exec that stops docker eating the admin answers, a `/dev/tty` probe that
opens the device rather than testing its permissions. None of that changes.

What it had never had was an audit of everything *around* those decisions, or
a single test. There is no CI in this repository, no shellcheck runner, not
even a `bash -n`. The only evidence the installer works is a sentence in
`docs/DEPLOYMENT.md` recording that somebody ran it by hand once.

The audit found three classes of problem.

**It dies silently.** Every `read` is an unguarded `set -e` trap door, so
Ctrl-D at any question exits mid-install with nothing printed. A hostname
typed at the "IP address:" prompt goes unvalidated into the certificate's SAN
as `IP:<hostname>`, `gen_intranet_cert.sh` fails, and its `2>/dev/null`
swallows openssl's explanation — the install ends with no output at all.

**It destroys and misreports.** `docker-compose.override.yml` is rewritten
unconditionally, while the header the installer writes *into that same file*
promises it will ask first; the file is gitignored, so on this host that
would silently take out the 8444 remap and the `/software` mounts with no way
back. `.env.bak.*` is not gitignored at all, so a reconfigure leaves the live
Postgres password and JWT secret somewhere `git add -A` would pick them up.
And choosing "keep the existing .env" on a re-run prints a summary claiming
localhost is the only URL and that only PySCF is available, on a deployment
that has both engines and publishes on the tailnet — because the variables
the summary reads are assigned only on the other branch.

**It goes quiet.** The health wait prints one line and then nothing for up to
five minutes, cannot distinguish "still importing" from "the container exited
thirty seconds ago", and then hard-fails, discarding an install that is one
`docker compose logs` away from working. `update.sh` carries the identical
loop.

Alongside those: a prompt that prints a literal `\n` on screen because
`printf '%s'` does not process escapes, a comment that ends mid-sentence, and
four documents that disagree with the script and with each other about its
prerequisites and how many steps it has.

Two decisions were the user's rather than mine. The certificate subject
hardcoded `O=Temple University/L=Philadelphia/ST=Pennsylvania`, so every
deployment anyone installed minted a certificate claiming to be Temple: it
becomes a derived `CN` with those fields dropped, shown for approval rather
than assumed. And the installer's hard refusal to run without a terminal is
what made it untestable end to end, so it gains a real scriptable mode rather
than a test harness that fakes one.

---

## Phase 1: One library, two deployment scripts

- [done] P1.1: `scripts/lib/common.sh` — colours behind a TTY guard, helpers,
  `envset`, preflight, the health wait
  evidence: scripts/lib/common.sh → "one library replaces the copies in install.sh and update.sh; `docker run --rm -v $PWD:/mnt koalaman/shellcheck:stable -x scripts/install.sh scripts/lib/common.sh scripts/update.sh scripts/gen_intranet_cert.sh` reports nothing on any of the four"
- [done] P1.2: `install.sh` sources it, below the `exec` and never above it
  evidence: tests/backend/install_01_static.py → "27/27. Includes `install.sh does not define colour codes of its own` and `sourced with stdout redirected, the colour codes are empty -- 0 bytes of escape sequences`, which is the guard install.sh alone lacked"
- [done] P1.3: `update.sh` sources it before `main()` is entered, so a
  fast-forward cannot swap the library mid-run
  evidence: tests/backend/deploy_02_deployed_commit.py → "14/14 against update.sh sourcing the library, up from 11 checks before -- health_urls now lifted from scripts/lib/common.sh via the fixture's existing path= argument, so its five port-discovery cases cover install.sh too"

## Phase 2: Stop the silent deaths

- [done] P2.1: A step-aware `ERR`/`EXIT` trap that names the step, tails the
  api log, and restores terminal echo
  evidence: scripts/install.sh → "one EXIT trap named by step() replaces per-call-site guards; a non-zero exit prints `stopped unexpectedly during: <step>`, an interrupt prints `cancelled during: <step>`, and terminal echo is restored either way"
- [done] P2.2: `ask`/`ask_yn` survive EOF with a message instead of exiting
  evidence: tests/backend/install_02_units.py → "`end of input at a yes/no question fails loudly instead of exiting in silence` and the same for free text -- both exit 1 naming 'end of file' where a bare read previously exited under set -e printing nothing at all"
- [done] P2.3: Diff and ask before replacing `docker-compose.override.yml`
  evidence: scripts/install.sh → "an override differing from what the run would write is shown as a coloured diff and kept unless confirmed; an unattended run keeps it and names --force-override. The file's own header had promised this behaviour since it was written"
- [done] P2.4: `.env.bak.*` gitignored; `.env` and its backups `chmod 600`
  evidence: tests/backend/install_01_static.py → "`git check-ignore -v .env.bak.20260910-120000` now answers `.gitignore:47:.env.bak.*`, where it previously matched nothing; .env and each backup are chmod 600"
- [done] P2.5: Validate the manually entered address; stop `gen_intranet_cert.sh`
  swallowing openssl's stderr
  evidence: tests/backend/install_02_units.py → "all 11 non-addresses rejected including `lab-host.example.edu` and `localhost`; and with the guard bypassed, gen_intranet_cert.sh now prints openssl's own `bad ip address ... value=not-an-ip.example.edu` and a plain-English cause instead of exiting silently"
- [done] P2.6: Rebuild the closing summary from `.env` and `docker compose
  config` so the re-run path reports the truth
  evidence: scripts/install.sh → "the closing summary is rebuilt from `docker compose config` and health_urls(), so the keep-.env path reports the same engines and URLs as a fresh install rather than reading variables that only the other branch assigns"
- [done] P2.7: `--bind` no longer silently ignored on the keep-`.env` path
  evidence: scripts/install.sh → "keeping an existing .env with --bind given now warns that it is being ignored and says reconfiguring is how to change it"
- [done] P2.8: Ollama probe derived from `QC_AGENT_LLM_BASE_URL`
  evidence: scripts/install.sh → "the probe is derived from QC_AGENT_LLM_BASE_URL with host.docker.internal mapped to 127.0.0.1, so a deployment pointed at another machine's Ollama is no longer told its model is unreachable"
- [done] P2.9: `envset` escapes `&`, `\` and its delimiter; the DMRG step uses it
  evidence: tests/backend/install_02_units.py → "`p@ss&word|with#hash\and\backslash` round-trips through envset unchanged, and a 60-character hex secret is byte-identical on read-back; the old version silently spliced the matched text in wherever a value contained &"
- [done] P2.10: `readlink -f` engine paths, and prove the mount inside the container
  evidence: scripts/install.sh → "engine paths go through `readlink -f` before their directory becomes a bind mount, and after the stack is up `docker compose exec -T api test -x <path>` confirms each configured engine is executable inside the container"

## Phase 3: Preflight that fails in ten seconds, not ten minutes

- [done] P3.1: `docker info`, disk headroom, port 8443, `data/` writability
  evidence: scripts/lib/common.sh → "require_docker distinguishes a stopped daemon, a user not in the docker group (naming `sudo usermod -aG docker <user>`) and a wedged one (`timeout 15`); disk is reported as a measured number on both the docker root and the checkout; the port check is skipped when this deployment is the thing already holding the port"
- [done] P3.2: The same preflight runs from `update.sh`, which had none
  evidence: scripts/update.sh → "update.sh had no `command -v` check of any kind and now runs the same require_tools/require_docker before it touches the checkout, instead of failing part-way through an update on a host missing curl"

## Phase 4: Progress indicators

- [done] P4.1: A health wait that shows elapsed time and per-service state,
  bails early on an exited container, and stops rather than bootstrapping an
  admin against a dead stack
  evidence: scripts/lib/common.sh → "qc_wait_for_health prints a spinner, elapsed seconds and live per-service state; driven under a pty against an unreachable URL it rendered `- 4s elapsed, up to 7s api:healthy nginx:running postgres:healthy redis:healthy` and cleared the line on exit. A stopped container returns 2 immediately rather than waiting out the full timeout, and install.sh then skips the admin bootstrap rather than running psql against a dead stack"
- [done] P4.2: `health_urls()` into the library; install.sh stops hardcoding
  the port
  evidence: tests/backend/deploy_02_deployed_commit.py → "5 port-discovery checks now cover both scripts: a remapped host port is found (https://127.0.0.1:8444), a wildcard bind becomes a connectable address, and a stack compose cannot answer for falls back to 8443"
- [done] P4.3: `step()` numbers itself against a declared total
  evidence: tests/backend/install_02_units.py → "`steps number themselves against the declared total -- [1/3] [2/3] [3/3]` and `every banner is the same width regardless of title length -- all 3 banners are 72 characters`; the total drops to what remains when the keep-.env path skips four steps"
- [done] P4.4: The build announces its cost; the summary reports elapsed total
  evidence: scripts/install.sh → "the build step states that it takes ten to twenty minutes once, reports its own duration, and the summary reports the whole install's elapsed time via qc_elapsed_human"

## Phase 5: Fewer questions, and only true statements

- [done] P5.1: The literal `\n`, and the truncated comment
  evidence: tests/backend/install_01_static.py → "the DMRG prompt printed a literal backslash-n because printf '%s' does not process escapes -- confirmed by running it -- and the truncated `# nginx/nginx.conf parses BOTH server blocks unconditionally, including` comment is gone"
- [done] P5.2: The network step loses two questions and ten lines of git
  archaeology
  evidence: scripts/install.sh → "the network step asks one numbered question built from what this host actually has, replacing three yes/no questions; the ten-line paragraph about a listener removed in August 2026 becomes one sentence pointing at docs/DEPLOYMENT.md"
- [done] P5.3: Derived certificate subject, shown for approval
  evidence: scripts/gen_intranet_cert.sh → "subject is `/CN=${FQDN}` alone; the fixed country, state, locality and organisation are gone, and install.sh shows the derived name and takes enter or a replacement"
- [done] P5.4: A closing summary that says what to do next
  evidence: scripts/install.sh → "the summary names every reachable URL from health_urls(), says the admin account is the first login and where to invite others, lists the engines actually configured, and flags an empty knowledge base"
- [todo] P5.5: README, DEPLOYMENT, ARCHITECTURE and CHANGELOG agree with the
  script about prerequisites, prologue length and step count

## Phase 6: A test that runs, and a mode that can be scripted

- [done] P6.1: `--non-interactive`, with expensive and host-modifying answers
  defaulting off
  evidence: tests/backend/install_01_static.py → "--non-interactive refuses without --bind and names each missing NEXUSQC_ADMIN_* variable in turn; a too-short password is refused without the password appearing in the output; --pull-model and --install-updater default off in that mode"
- [done] P6.2: `tests/backend/install_01_static.py` — parse, prologue, `--help`,
  no-TTY refusal
  evidence: tests/backend/install_01_static.py → "27/27. The 192-line prologue parses under dash and contains none of the six bashisms checked for; --help through a real `dash -s --` pipe exits 0 and clones nothing"
- [done] P6.3: `tests/backend/install_02_units.py` — the library's functions
  against awkward input
  evidence: tests/backend/install_02_units.py → "21/21 across envset escaping, valid_ipv4 (6 accepted, 11 rejected), ask/ask_yn including both end-of-input cases, and step numbering"
- [todo] P6.4: End to end in a scratch clone, both modes, plus the provoked
  failure paths

---

## What the end-to-end run caught that nothing else did

Worth recording, because it is the argument for the whole of Phase 6.

The rewritten `ask()` ended with `[ -z "$REPLY" ] && REPLY="$default"`. As the
last command of a function that returns the test's own status, so any non-empty
answer made `ask()` return 1 and `set -e` killed the installer immediately. The
interactive path was broken at the first question a person actually types into.

Three layers of checking passed anyway:

- **shellcheck** was clean. The construct is idiomatic and correct anywhere but
  the last line of a function.
- **The unattended install came up healthy in 3m41s.** `--non-interactive`
  skips every prompt, so it never called `ask()` once.
- **The unit test passed.** It sent an empty line, which is the one input for
  which the test is true and the function returns 0.

Only driving the real prompts on a real terminal found it, and it found it in
the first thirty seconds. The fix is an `if` and an explicit `return 0`; the
test now covers a typed answer, an answer with no default, and asserts that
every function the library exports returns 0 on success, since one instance of
this class shipped and the class is the thing worth asserting.

A second, smaller version of the same lesson: the first two attempts to verify
the fix failed identically, because `tests/install_interactive.py` sets its
scratch deployment up with `git clone`, and a local clone takes the committed
`HEAD` rather than the working tree. It now copies any modified tracked file
over the clone and names each one, so a pass is a pass for the code being
edited.

## Incidental findings

Logged here rather than fixed silently or lost in conversation.

- [todo] The colour block and `die/ok/info/warn/step` are copy-pasted across
  seven scripts (`install.sh`, `update.sh`, `install_updater.sh`,
  `extract_frontend.sh`, `release.sh`, `check_destructive.sh`,
  `check_public_safe.sh`). This plan moves two of them onto a shared library
  and deliberately leaves the other five: `release.sh` and the two checkers
  gate publication to the public remote, and destabilising them for tidiness
  is a bad trade. Worth doing later, on its own.
- [todo] `update.sh` has no preflight tool check of any kind, so a host
  missing `curl` or `openssl` fails part-way through an update rather than
  before it starts. Phase 3 fixes this as a side effect of sharing the
  preflight, which is the only reason it is not a separate plan.

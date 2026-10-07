# Handoff

Work that finished in a session but still needs a person, or a machine, to
do something before it is really done. A session cannot see the previous
session's conversation, so anything left half-landed has to be written here
or it is lost.

Delete an entry once it is done. An empty "Open" section is the normal
state of this file.

## Open

- **The QUESTDB benchmark run is live; re-arm its monitors.** Launched
  2026-10-07 05:48 UTC as a detached runner (`setsid`), so it survives the
  session that started it, and its state is on disk under
  `.cache/casbench_quest/run/main/`. Measured estimate about six days at ten
  parallel calculations, longer while other tenants load the host. A new
  session should, from the repo root with the `qc-agent` environment:
  `scripts/casbench/quest_ctl.sh status main` for progress; if the runner is
  gone without `RUN_COMPLETE` in `runner.log` (after a reboot, say),
  `scripts/casbench/quest_ctl.sh resume main`, which skips finished rows and
  adopts any worker still running; then re-arm the two monitors the user
  asked for, which live only in a session: an hourly status check (CronCreate)
  and an event Monitor on `scripts/casbench/quest_watch.sh main`. The
  remaining plan steps are P4.3 onward in `docs/TRACKER.md`. Remove this
  entry when the run completes.

- **Decide whether the development host's Docker daemon should stop using
  its userland port proxy.** On that host a `docker-proxy` process accepts
  every connection to the published nginx port, so nginx, and through it the
  app, sees every client as the bridge gateway address. The whole research
  group therefore shares one client address. Since 2026-09-24 login is rate
  limited per account as well as per address, so one person's typos no longer
  lock the others out, but anything else keyed on the client address still
  treats the group as one client. The fix is `"userland-proxy": false` in the
  daemon's `daemon.json` and a daemon restart. That file is root-owned and
  shared by every tenant on the machine, and the restart stops every
  container on it, so it is a decision for a person, not a session. After
  it, `docker compose logs nginx` should show real client addresses.

- **Re-verify BAGEL's orbital reuse mapping on a host where BAGEL runs.**
  `tests/backend/active_04_engine_records.py` with `ACTIVE_04_LIVE_BAGEL=1`
  runs a water/STO-3G CASSCF(4,4) source and a destination that reuses it
  through `load_ref` naming the source's own window, and asserts the
  destination's `reference_orbital_weights` are all above 0.9. That is the
  one measurement that shows the `save_ref` archive and the printed molden
  order their orbitals the same way. On this host it cannot run: on
  2026-09-20 the source CASSCF converged in 16 macro-iterations (about 76 s
  each, E = -74.98699597) and BAGEL then died in its molden `print` block
  with `dsyev/pdsyevd failed in Matrix`, the MKL crash `CLAUDE.local.md`
  records, so neither the molden nor the archive was written. The code
  path is structurally confirmed (the `active` keyword reaches the input,
  the window is recorded from `nclosed` even without an export); the live
  weights are what is missing.


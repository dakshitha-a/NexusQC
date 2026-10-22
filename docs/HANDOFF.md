# Handoff

Work that finished in a session but still needs a person, or a machine, to
do something before it is really done. A session cannot see the previous
session's conversation, so anything left half-landed has to be written here
or it is lost.

Delete an entry once it is done. An empty "Open" section is the normal
state of this file.

## Open

- **Run `scripts/update.sh` to deploy four approval-card, plot and
  troubleshooting fixes, then refilm the README tour.** The session that
  made them (2026-10-22, tracker step P1A.4) could not run the update; the
  auto-mode permission check refused it. The dry run passed every gate,
  with no jobs running. After it, `node tests/frontend/tour/tour.mjs hero
  hero-light asks molecule orbitals spectrum vibrations plots troubleshoot
  active-space projects` refilms every clip into `docs/tour/`. The new
  README waits on those clips; a draft of it is not in the repository yet.

- **Decide what to do with the QUESTDB benchmark result.**
  The benchmark is finished and committed (`docs/casbench/questdb.md`).
  The user has to decide whether to act on the engine missing all 12
  aza-naphthalene n→π* states, which is logged as an open finding in
  `docs/trackers/2026-10-questdb-benchmark.md`. The engine fix it waited
  on is deployed: on 2026-10-22 the stack was already running 0d9706a.

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


# Handoff

Work that finished in a session but still needs a person, or a machine, to
do something before it is really done. A session cannot see the previous
session's conversation, so anything left half-landed has to be written here
or it is lost.

Delete an entry once it is done. An empty "Open" section is the normal
state of this file.

## Open

- **Read the detached BAGEL orbital-reuse run started 2026-11-10 20:37 EST.**
  It runs outside any session, as `setsid nohup` under `systemd --user`, from
  `<scratch>/bagel-orbital-check/` (`run.sh`, `status`,
  `active_04.log`; its scratch data dir is `data/` there, not the stack's).
  `status` gains a "finished" line when it ends. If `active_04.log` shows the
  destination's `reference_orbital_weights` all above 0.9, the entry below is
  verified and both can be closed. The run uses the library path a fresh
  login now gets: on 2026-11-10 host-shell BAGEL was found loading
  TeraChem's 2011-era `libiomp5.so` ahead of oneAPI 2025.3's, because
  `~/.bashrc` prepended TeraChem's lib after sourcing oneAPI; the user had
  it changed to append (backup `~/.bashrc.bak-20261110-nexusqc`). The
  container was never affected. Compare this run's iteration time and MKL
  warnings with the mismatched one (about 70 s per macro-iteration and
  repeated `Parameter 9 was incorrect on entry to cblas_dgemm`). Delete the
  directory when done.

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


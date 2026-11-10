# Handoff

Work that finished in a session but still needs a person, or a machine, to
do something before it is really done. A session cannot see the previous
session's conversation, so anything left half-landed has to be written here
or it is lost.

Delete an entry once it is done. An empty "Open" section is the normal
state of this file.

## Open

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


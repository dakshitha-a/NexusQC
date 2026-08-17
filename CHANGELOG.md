# Changelog

All notable changes to NexusQC are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

This file is load-bearing, not decoration: `scripts/release.sh` refuses to
publish a version that has no section here, so a release cannot happen without a
note saying what changed.

## [Unreleased]

## [1.0.0] - 2026-08-17

First public release.

### Added

- Conversational agent over PySCF, ORCA and BAGEL, with every calculation gated
  behind a structural human approval step rather than a prompt instruction.
- Job types: single-point, geometry optimisation, frequencies, combined
  optimisation + frequencies, CASSCF, CASPT2, TDDFT/TDA/CIS/TD-HF, EOM-CCSD,
  conical-intersection optimisation, potential-energy scans, NEB transition-state
  search, orbital visualisation, active-space recommendation, nuclear-ensemble
  (Wigner) absorption spectra, and raw custom ORCA/BAGEL input.
- Basis Set Exchange integration: an offline, per-engine-translated escape hatch
  for exact published basis sets, including general-contraction handling for
  BAGEL and `%basis NewGTO` generation for ORCA.
- Multi-user deployment: Postgres, Redis and nginx via Docker Compose,
  invite-only registration, per-user ownership isolation, storage quotas, an
  append-only admin audit log, and an admin console covering invites, users and
  bug reports.
- Retrieval-augmented knowledge base over engine manuals, consulted mechanically
  on every job-input generation rather than at the model's discretion.
- `scripts/check_public_safe.sh` and a pre-push hook, so host-specific paths and
  credentials cannot reach a public remote by being forgotten.

### Fixed

- Wigner sampling applied `1/sqrt(mu)` twice, making every displacement too small
  by `sqrt(mu)` — about 4% for a hydrogen-dominated mode, but a factor of 2.2 for
  a 5 amu C=O stretch and 3.4 for the heaviest modes of a twelve-atom molecule.
  The reduced-mass helper separately fabricated `mu = 1.0 amu` for every ORCA
  mode, because ORCA's printed normal modes are unit-normalised where PySCF's are
  mass-deweighted. Both are replaced by a rescaling-invariant reduced mass paired
  with an explicitly unit-normalised direction.
- `job_context_summary` omitted a completed job's own method and basis, so "use
  the same method as the attached job" was unanswerable by any tool the agent had.
- The pre-push history scan could report a pass having examined nothing, on the
  two pushes it exists to guard: a first push to a remote that has never seen the
  branch, and a force-push after a history rewrite. In both cases the revision
  range failed to resolve, the error was discarded, and an empty commit list read
  as "this push touches nothing". An unresolvable range is now a hard error, and
  the hook recognises an unknown remote tip and widens the scan to every commit
  being pushed instead of narrowing it to none.
- The same scan blocked on its own redaction placeholders once run against the
  rewritten history, and blocked permanently on regenerable test telemetry that a
  later commit had already deleted. The placeholder exemptions are narrow and
  commented; the telemetry rule now warns about history while still blocking the
  working tree, because a hygiene rule that immutable history cannot satisfy is
  one that gets bypassed along with the rules that matter.

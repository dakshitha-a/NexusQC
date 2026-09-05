"""The mean field the whole engine is built on, converged to one answer.

Everything downstream of here reads a converged SCF: the projector takes its
orbitals, the ranking takes its Fock and exchange matrices, the refinement
rebuilds a recorded specification against it. So if the SCF itself has more than
one converged solution, every one of those inherits the ambiguity, and the
engine returns a different active space on identical input.

That is not hypothetical. Plain RHF on twisted ethylene converges to two
solutions 31.5 mHa apart, reporting success on both. One of the projector's
eigenvalues for that molecule sits within about 0.02 of the 0.2 admission
threshold, so which solution the SCF found decides which side of the cut the
eigenvalue lands on, and admitting one occupied orbital is exactly the
difference between CAS(2e,2o) and CAS(4e,3o). Measured over sixty runs, 51
returned the first and 9 the second.

**A converged SCF is not necessarily a stable one.** `converged` means the
iterations stopped moving, and an unstable solution is a stationary point that
is not a minimum, so it satisfies that test perfectly. Asking for stability
separately, and following the instability until it is gone, is what makes the
reference well defined. Over twenty repeats it collapses twisted ethylene from
17-and-3 across two solutions to 20 of 20 on the lower one, and it changes no
benchmark molecule's recommended space except twisted ethylene's, which changes
to the space its reference reports.

Three molecules move to a lower solution without being ambiguous to begin with:
square cyclobutadiene by 11.4 mHa, stretched N2 by 19.1 mHa, and O2 by 0.25.
None of them changes its recommended space, which is the evidence that this is
a repair rather than a perturbation.

**Internal instabilities are followed; external ones are reported.** An external
instability means the closed-shell reference is unstable toward an open-shell
one, which is the honest description of a singlet diradical and is true of every
diradical in the benchmark. Acting on it means a broken-symmetry reference, and
`projector.project` takes the alpha set alone when handed one, so following it
would silently change what the projection means. That is a design decision, not
a repair, so it is surfaced to the user and left to them.
"""
from __future__ import annotations

from dataclasses import dataclass, field

# How many times to follow an internal instability before giving up. Each pass
# is a fresh SCF from the improved orbitals. Anything that has not settled in a
# few passes is not going to, and the result says so rather than looping.
MAX_FOLLOW = 5


@dataclass
class Stability:
    """What had to be done to the reference, and what remains wrong with it."""

    followed: int = 0                  # instabilities followed to convergence
    internal_stable: bool | None = None
    external_stable: bool | None = None    # None when it could not be asked
    energy_before: float | None = None
    energy_after: float | None = None
    notes: list = field(default_factory=list)

    @property
    def moved(self) -> bool:
        if self.energy_before is None or self.energy_after is None:
            return False
        return abs(self.energy_after - self.energy_before) > 1e-9

    def to_dict(self) -> dict:
        return {
            "followed": self.followed,
            "internal_stable": self.internal_stable,
            "external_stable": self.external_stable,
            "energy_before": self.energy_before,
            "energy_after": self.energy_after,
            "notes": list(self.notes),
        }


def _ask(mf, external: bool):
    """`stability()` with its return shape normalised.

    Two things vary between reference classes and pyscf versions and neither is
    safe to assume. The tuple is two entries without `return_status` and four
    with it, and the external entries are `None` unless `external=True` was
    asked for -- which is a trap worth naming, because `not None` is true, so a
    test written as `if not stable_e` reports an instability on every molecule
    from a quantity that was never computed.

    `rohf_external` raises `NotImplementedError` in pyscf, so an open-shell
    reference cannot answer the external question at all.
    """
    try:
        out = mf.stability(external=external, return_status=True)
    except NotImplementedError:
        if not external:
            raise
        out = mf.stability(external=False, return_status=True)
        return out[0], (out[2] if len(out) == 4 else None), "unavailable"
    if len(out) == 4:
        return out[0], out[2], out[3]
    return out[0], None, None


def stabilise(mf, *, check_external: bool = True, log=None) -> Stability:
    """Re-converge `mf` until it is internally stable, and report on it.

    Mutates `mf` in place, which is what every caller wants: they hold the
    object the rest of the pipeline reads.
    """
    report = Stability(energy_before=float(mf.e_tot))

    # Both questions are asked in one call. Asking for the external check
    # separately afterwards would repeat the internal analysis, which is the
    # expensive half and already has its answer: on anthracene that is 45
    # seconds paid twice for one number.
    for _ in range(MAX_FOLLOW):
        mo, stable_i, stable_e = _ask(mf, external=check_external)
        report.internal_stable = stable_i
        report.external_stable = None if stable_e == "unavailable" else stable_e
        if stable_i is not False:
            break
        mf.kernel(dm0=mf.make_rdm1(mo, mf.mo_occ))
        report.followed += 1
        if log:
            log(f"followed an internal instability to E = {mf.e_tot:.8f} Ha")
    else:
        report.notes.append(
            f"The reference was still unstable after {MAX_FOLLOW} attempts to "
            f"correct it, so the active space below rests on a mean field that "
            f"is not a minimum. Treat it as provisional."
        )

    report.energy_after = float(mf.e_tot)

    if report.moved and log:
        drop = (report.energy_before - report.energy_after) * 1000.0
        log(f"the reference was not stable; re-converged {drop:.1f} mHa lower")

    if report.external_stable is False:
        report.notes.append(
            "The closed-shell reference is unstable toward an open-shell one. "
            "That is expected for a diradical or a stretched bond, and it means "
            "the single-determinant starting point is qualitatively poor even "
            "though it converged. The active space is built from the lowest "
            "closed-shell solution, which is well defined; a broken-symmetry "
            "reference would describe the ground state better and is a "
            "different calculation, not a correction to this one."
        )

    return report

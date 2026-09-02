"""How big the space is, what it will cost, and which engines can run it.

There is deliberately no cap here. The legacy runners refused any request above
twelve active orbitals, and that ceiling was not a statement about chemistry:
it existed because each recommendation ended in a full state-averaged CASSCF,
so the recommendation itself had to stay inside what CASSCF could afford. This
engine does not run that CASSCF, so the constraint is gone with it.

What replaces it is an honest cost statement. A space is reported with its
determinant and CSF counts and the engines that can actually run it, and a
space that is too large for anything gets a warning rather than an exception.
Refusing is the wrong response in this project: a long calculation is the
design premise, not a defect, and the user is better served by "this is
(24e,24o), about 10^12 CSFs, no engine here will finish it" than by an error
that hides the number.

Counting
--------
The determinant count for :math:`N_\\alpha` alpha and :math:`N_\\beta` beta
electrons in :math:`n` orbitals is the obvious product of binomials,

.. math::

    N_{\\mathrm{det}} = \\binom{n}{N_\\alpha}\\binom{n}{N_\\beta}

but the quantity that actually sets the cost of a spin-adapted CI -- which is
what pyscf's CSF solver and every CASSCF implementation here uses -- is the
number of configuration state functions of the right total spin. That is the
Weyl-Paldus dimension,

.. math::

    N_{\\mathrm{CSF}}(n, N, S) = \\frac{2S + 1}{n + 1}
        \\binom{n + 1}{N/2 - S}\\binom{n + 1}{N/2 + S + 1}

which for a singlet is smaller than the determinant count by roughly a factor
of :math:`N/2`, and the difference matters when deciding whether something is
runnable. The legacy code used ``comb * comb`` minus a correction, which is the
same number for a singlet but does not generalise to arbitrary spin.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import comb

# Rough, deliberately generous ceilings on the number of CSFs each route can
# handle on this class of hardware. They exist to shape a warning, never to
# refuse, so being approximate is fine; the NEVPT2 orbital ceiling is the one
# hard-ish number, taken from docs/QM_CAPABILITIES.md.
ENGINE_LIMITS = (
    # (label, max_csf, max_orbitals, note)
    ("CASSCF (PySCF/ORCA/BAGEL)", 5e7, 20,
     "a conventional CASSCF; beyond about 18 orbitals expect hours per macro-iteration"),
    ("CASPT2 (BAGEL)", 5e6, 16,
     "CASPT2 adds a large constant factor over the CASSCF it starts from"),
    ("NEVPT2 (PySCF)", 5e6, 26,
     "strongly contracted NEVPT2; the orbital ceiling is the practical one here"),
    ("DMRG-CI (block2)", 1e30, 60,
     "cost is polynomial in the orbital count rather than combinatorial, so the "
     "CSF number stops being the limit"),
)


def n_determinants(n_orb: int, n_alpha: int, n_beta: int) -> int:
    if n_alpha > n_orb or n_beta > n_orb or min(n_alpha, n_beta) < 0:
        return 0
    return comb(n_orb, n_alpha) * comb(n_orb, n_beta)


def n_csf(n_orb: int, n_elec: int, spin_2s: int = 0) -> int:
    """Weyl-Paldus dimension: CSFs of total spin S = spin_2s/2.

    Returns 0 for a combination that cannot be formed, rather than raising --
    an impossible space is a thing to report, not to crash on.
    """
    s2 = spin_2s / 2.0
    if n_elec < 0 or n_elec > 2 * n_orb:
        return 0
    a = n_elec / 2.0 - s2
    b = n_elec / 2.0 + s2 + 1
    if a < 0 or abs(a - round(a)) > 1e-9:
        return 0
    a, b = int(round(a)), int(round(b))
    if a > n_orb + 1 or b > n_orb + 1:
        return 0
    return int(round((2 * s2 + 1) / (n_orb + 1) * comb(n_orb + 1, a) * comb(n_orb + 1, b)))


@dataclass
class Feasibility:
    n_orbitals: int
    n_electrons: int
    spin_2s: int
    n_determinants: int
    n_csf: int
    runnable_on: list
    warnings: list

    def summary_line(self) -> str:
        where = ", ".join(self.runnable_on) if self.runnable_on else "no engine here"
        return (f"({self.n_electrons}e, {self.n_orbitals}o): "
                f"{self.n_csf:,} CSFs, {self.n_determinants:,} determinants; "
                f"runnable on {where}")

    def to_dict(self) -> dict:
        return {
            "n_orbitals": self.n_orbitals,
            "n_electrons": self.n_electrons,
            "n_determinants": self.n_determinants,
            "n_csf": self.n_csf,
            "runnable_on": list(self.runnable_on),
            "warnings": list(self.warnings),
        }


def assess(n_orb: int, n_elec: int, spin_2s: int = 0) -> Feasibility:
    """Size, cost and reachable engines for a space. Never raises on size."""
    n_beta = (n_elec - spin_2s) // 2
    n_alpha = n_elec - n_beta
    ndet = n_determinants(n_orb, n_alpha, n_beta)
    ncsf = n_csf(n_orb, n_elec, spin_2s)

    runnable, warnings = [], []
    for label, max_csf, max_orb, note in ENGINE_LIMITS:
        if ncsf and ncsf <= max_csf and n_orb <= max_orb:
            runnable.append(label)

    if not runnable:
        warnings.append(
            f"({n_elec}e, {n_orb}o) is {ncsf:,} CSFs, beyond what any engine "
            f"configured here will finish. The recommendation still stands as "
            f"the chemically correct space; running it needs either a smaller "
            f"tier or a DMRG treatment."
        )
    elif len(runnable) == 1 and runnable[0].startswith("DMRG"):
        warnings.append(
            f"({n_elec}e, {n_orb}o) is too large for conventional CASSCF here "
            f"({ncsf:,} CSFs); only a DMRG-CI treatment will reach it."
        )
    if n_elec == 2 * n_orb and n_orb:
        warnings.append(
            "Every orbital is doubly occupied, so this space holds exactly one "
            "configuration and describes no correlation."
        )
    if n_orb and n_elec == 0:
        warnings.append("This space has no electrons in it.")
    return Feasibility(n_orb, n_elec, spin_2s, ndet, ncsf, runnable, warnings)

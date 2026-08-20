"""What each (engine, method) pair can actually do on this host.

Transcribed from [`docs/QM_CAPABILITIES.md`](../../../docs/QM_CAPABILITIES.md),
which is the human-verified record of real calculations run by
`scripts/spikes/spike_{pyscf,orca,bagel}_caps.py` during Phase 0. From
Phase 1 onward the direction of authority reverses: this module is the
source and `scripts/generate_capability_docs.py` regenerates the tables in
that document from it, with `scripts/check_capability_matrix.py` failing on
drift.

**Every cell carries its own evidence level**, because a row is rarely
uniformly verified: PySCF's HF gradient was executed here, while its
excited-state gradient was executed only with a DFT reference and the HF
(CIS) case rests on the module's documented behaviour. Recording one level
for a whole row would have to round in one direction or the other, and both
directions are wrong -- rounding up invents verification, rounding down
would have the routing table refuse things this host demonstrably does.

The negatives matter as much as the positives and are deliberately recorded
with the same provenance:

- BAGEL has **no** constrained optimization. `fix_atom` is accepted, exits
  0, and moves the supposedly frozen atom anyway; the spike proved it by
  differential geometry comparison rather than by exit status.
- PySCF's CASSCF has no analytic Hessian, so this app's hand-rolled
  numerical one is load-bearing rather than redundant.
- ORCA's `%casscf` block rejects `NACME` in this build. What works is the
  CIS/TDDFT module's ground-to-excited coupling.
- Nothing here does a TDDFT NAC, and only BAGEL and ORCA do conical
  intersections.

Nothing may claim a capability at `unverified`: `MethodCaps.has()` treats
`unverified` and `gap` as unavailable, so an untested claim can never route
a job.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Optional

# Engines in this app's own preference order -- see routing.ENGINE_PREFERENCE,
# which is the single place that order is acted on.
ENGINES = ("pyscf", "orca", "bagel")

# The canonical electronic-structure methods. Deliberately NOT the same
# vocabulary as the legacy `JobSpec.method` field, which conflates method
# with task ("tddft", "casscf" and "single_point" are all values of one
# field there). Here the method is only ever the level of theory; what is
# being computed with it lives in tasks.py. CIS/TDA/TDDFT are not methods:
# they are `hf`/`dft` plus the `use_tda` parameter, exactly as the runners
# already treat them.
CANONICAL_METHODS = ("hf", "dft", "mp2", "ccsd", "eom_ccsd", "casscf", "caspt2")

# Evidence levels, weakest last. `gap` means it was attempted here and the
# datum could not be located or the syntax was rejected -- strictly worse
# than `unverified` as a claim, because we know it did not work.
EVIDENCE_LEVELS = ("run", "manual", "unverified", "gap")

# Levels a capability claim may rest on. `unverified` and `gap` are
# excluded on purpose: the routing table must never offer a user something
# on the strength of nobody having checked.
TRUSTED_LEVELS = frozenset({"run", "manual"})

# The capability fields, in the order the generated documentation tables
# present them. Kept as a tuple so the doc generator and the drift check
# iterate the same list in the same order without either owning it.
CAPABILITY_FIELDS = (
    "energy", "excited", "osc_strengths", "gradient", "excited_gradient",
    "hessian", "nac", "ci_opt", "constrained_opt",
)


@dataclass(frozen=True)
class Evidence:
    """Provenance for one capability cell."""
    level: str
    observed: str
    source: str = ""

    def __post_init__(self) -> None:
        if self.level not in EVIDENCE_LEVELS:
            raise ValueError(f"unknown evidence level {self.level!r}")

    @property
    def trusted(self) -> bool:
        return self.level in TRUSTED_LEVELS


_UNVERIFIED = Evidence("unverified", "no recorded provenance")


@dataclass(frozen=True)
class MethodCaps:
    """Properties of one (engine, method) pair.

    Every field is a *property of the physics/software*, never a policy
    choice about what this app offers. Task availability is derived from
    these by `tasks.supports()`; nothing hand-enumerates "engine X can run
    job type Y".
    """
    engine: str
    method: str
    energy: bool = True
    excited: bool = False
    osc_strengths: bool = False
    gradient: Optional[str] = None          # "analytic" | "numerical" | None
    excited_gradient: bool = False
    hessian: Optional[str] = None           # "analytic" | "numerical" | None
    nac: bool = False
    ci_opt: bool = False
    constrained_opt: bool = False
    notes: str = ""
    source: str = ""
    evidence: Mapping[str, Evidence] = field(default_factory=dict)

    @property
    def key(self) -> tuple[str, str]:
        return (self.engine, self.method)

    def level_for(self, capability: str) -> str:
        """Evidence level for one capability field, `unverified` if the
        cell has no recorded provenance."""
        return self.evidence.get(capability, _UNVERIFIED).level

    def has(self, capability: str) -> bool:
        """True only when the capability is both present AND rests on
        trusted evidence. This is the single gate every derived verdict
        goes through, which is what keeps an `unverified` cell from ever
        being routed to."""
        value = getattr(self, capability)
        present = value is not None and value is not False
        return bool(present) and self.evidence.get(capability, _UNVERIFIED).trusted

    @property
    def verified(self) -> str:
        """Weakest evidence level among the capabilities this row actually
        claims -- the row-level summary the plan asks for, derived rather
        than maintained by hand so it cannot drift from the cells."""
        claimed = [c for c in CAPABILITY_FIELDS
                   if getattr(self, c) is not None and getattr(self, c) is not False]
        if not claimed:
            return "unverified"
        order = {lvl: i for i, lvl in enumerate(EVIDENCE_LEVELS)}
        return max((self.level_for(c) for c in claimed), key=lambda lvl: order[lvl])


_PYSCF_SPIKE = "scripts/spikes/spike_pyscf_caps.py"
_ORCA_SPIKE = "scripts/spikes/spike_orca_caps.py"
_BAGEL_SPIKE = "scripts/spikes/spike_bagel_caps.py"
_MANUALS = "data/scraped/"


def _ev(level: str, observed: str, source: str) -> Evidence:
    return Evidence(level=level, observed=observed, source=source)


# --------------------------------------------------------------- PySCF 2.14

_PYSCF: tuple[MethodCaps, ...] = (
    MethodCaps(
        engine="pyscf", method="hf",
        energy=True, excited=True, osc_strengths=True,
        gradient="analytic", excited_gradient=True, hessian="analytic",
        nac=False, ci_opt=False, constrained_opt=True,
        notes="Excited states are CIS/TD-HF through the same tdscf module DFT uses "
              "(use_tda selects CIS vs TD-HF).",
        source=_PYSCF_SPIKE,
        evidence={
            "energy": _ev("run", "RHF/STO-3G converged", _PYSCF_SPIKE),
            "excited": _ev("manual", "pyscf.tdscf takes an RHF reference; the spike exercised "
                                     "the DFT reference only", _PYSCF_SPIKE),
            "osc_strengths": _ev("manual", "same tdscf oscillator-strength path as the DFT "
                                           "reference, which was run here", _PYSCF_SPIKE),
            "gradient": _ev("run", "|grad| = 0.086934 Eh/Bohr, shape (3,3)", _PYSCF_SPIKE),
            "excited_gradient": _ev("manual", "tdscf gradients exist for an RHF reference; run "
                                              "here with DFT only", _PYSCF_SPIKE),
            "hessian": _ev("run", "3 modes, max 4812.5 cm-1", _PYSCF_SPIKE),
            "constrained_opt": _ev("run", "geomeTRIC 1.1.1 kernel() exposes constraints", _PYSCF_SPIKE),
        },
    ),
    MethodCaps(
        engine="pyscf", method="dft",
        energy=True, excited=True, osc_strengths=True,
        gradient="analytic", excited_gradient=True, hessian="analytic",
        nac=False, ci_opt=False, constrained_opt=True,
        notes="No TDDFT non-adiabatic couplings: there is no pyscf.nac.tdscf in 2.14, and "
              "pyscf-forge did not add one.",
        source=_PYSCF_SPIKE,
        evidence={
            "energy": _ev("run", "B3LYP/STO-3G converged", _PYSCF_SPIKE),
            "excited": _ev("run", "TDDFT and TDA both produced 3 states", _PYSCF_SPIKE),
            "osc_strengths": _ev("run", "f = [2.37e-3, ~0, 6.34e-2]", _PYSCF_SPIKE),
            "gradient": _ev("run", "|grad| computed for B3LYP", _PYSCF_SPIKE),
            "excited_gradient": _ev("run", "|grad(S1)| = 0.6027 (full TDDFT), 0.6035 (TDA). WB97X (no "
                                           "dispersion) also ran clean (|grad(S1)|=0.5508). WB97X-D and "
                                           "WB97X-D3 both raise NotImplementedError ('... is not "
                                           "supported yet') from the TDDFT gradient driver despite "
                                           "pyscf.dft.libxc.parse_xc accepting 'wb97x-d' as a name -- "
                                           "parsing the name and actually running a gradient with it are "
                                           "different claims here (see docs/PARSER_GAPS.md). Notably "
                                           "'wb97x-d' is accepted by PySCF's own libxc parser but "
                                           "REFUSED BY ORCA's input check as an unrecognized keyword --"
                                           " the same free-text string is invalid on each engine for the "
                                           "opposite reason.",
                                    _PYSCF_SPIKE),
            "hessian": _ev("run", "3 modes, B3LYP max 4697.1 cm-1", _PYSCF_SPIKE),
            "nac": _ev("gap", "importing pyscf.nac.tdscf fails in 2.14", _PYSCF_SPIKE),
            "constrained_opt": _ev("run", "geomeTRIC 1.1.1 kernel() exposes constraints", _PYSCF_SPIKE),
        },
    ),
    MethodCaps(
        engine="pyscf", method="mp2",
        energy=True, gradient="analytic", constrained_opt=True,
        notes="Ground state only. No analytic MP2 Hessian is wired up here, so frequencies "
              "are not offered for MP2.",
        source=_PYSCF_SPIKE,
        evidence={
            "energy": _ev("run", "MP2 on an RHF reference converged", _PYSCF_SPIKE),
            "gradient": _ev("run", "|grad| computed via mp.MP2(...).nuc_grad_method()", _PYSCF_SPIKE),
            "constrained_opt": _ev("manual", "geomeTRIC drives any method exposing a gradient; run "
                                             "here with HF", _PYSCF_SPIKE),
        },
    ),
    MethodCaps(
        engine="pyscf", method="ccsd",
        energy=True, gradient="analytic", constrained_opt=True,
        notes="Ground state only; excited states are the separate eom_ccsd method.",
        source=_PYSCF_SPIKE,
        evidence={
            "energy": _ev("run", "CCSD on an RHF reference converged", _PYSCF_SPIKE),
            "gradient": _ev("run", "|grad| computed via cc.CCSD(...).nuc_grad_method()", _PYSCF_SPIKE),
            "constrained_opt": _ev("manual", "geomeTRIC drives any method exposing a gradient; run "
                                             "here with HF", _PYSCF_SPIKE),
        },
    ),
    MethodCaps(
        engine="pyscf", method="eom_ccsd",
        energy=True, excited=True, osc_strengths=False,
        notes="Energies only. PySCF's EOMEESinglet returns no transition dipoles, so an "
              "oscillator strength would have to be fabricated -- ORCA is the default engine "
              "for this method for exactly that reason.",
        source=_PYSCF_SPIKE,
        evidence={
            "energy": _ev("manual", "pyscf.cc EOM-EE-CCSD is in use by this app's runner", _PYSCF_SPIKE),
            "excited": _ev("manual", "EOMEESinglet returns excitation energies", _PYSCF_SPIKE),
            "osc_strengths": _ev("gap", "no transition dipoles exposed by EOMEESinglet", _PYSCF_SPIKE),
        },
    ),
    MethodCaps(
        engine="pyscf", method="casscf",
        energy=True, excited=True, osc_strengths=False,
        gradient="analytic", excited_gradient=False, hessian="numerical",
        nac=True, ci_opt=False, constrained_opt=True,
        notes="The only engine here with an analytic SA-CASSCF NAC. No analytic Hessian "
              "('CASSCF' object has no attribute 'Hessian'), which is why this app's own "
              "numerical CASSCF Hessian exists. No MECI optimizer: pyscf.geomopt.meci does "
              "not exist and one would have to be written on top of geomeTRIC.",
        source=_PYSCF_SPIKE,
        evidence={
            "energy": _ev("run", "CASSCF(4,4)/STO-3G converged", _PYSCF_SPIKE),
            "excited": _ev("run", "state-averaged CASSCF produced 2 states", _PYSCF_SPIKE),
            "osc_strengths": _ev("gap", "SA-CASSCF states available but transition dipoles need "
                                        "manual assembly -- no ready API", _PYSCF_SPIKE),
            "gradient": _ev("run", "|grad| computed via mc.nuc_grad_method()", _PYSCF_SPIKE),
            "hessian": _ev("run", "analytic Hessian absent ('CASSCF' object has no attribute "
                                  "'Hessian'); this app's numerical CASSCF Hessian is the "
                                  "working path", _PYSCF_SPIKE),
            "nac": _ev("run", "pyscf.nac.sacasscf returns (natm,3) and scales as 1/dE across a "
                              "gap scan (2.0e-6 at 10.6 eV -> 2.4e-5 at 0.26 eV)", _PYSCF_SPIKE),
            "ci_opt": _ev("gap", "no pyscf.geomopt.meci", _PYSCF_SPIKE),
            "constrained_opt": _ev("run", "geomeTRIC 1.1.1 kernel() exposes constraints", _PYSCF_SPIKE),
        },
    ),
)

# ---------------------------------------------------------------- ORCA 6.1.1

_ORCA: tuple[MethodCaps, ...] = (
    MethodCaps(
        engine="orca", method="hf",
        energy=True, excited=True, osc_strengths=True,
        gradient="analytic", excited_gradient=True, hessian="analytic",
        nac=True, ci_opt=True, constrained_opt=True,
        notes="Excited states are CIS/TD-HF via the same %tddft block DFT uses. The NAC is "
              "ground-to-excited only -- ORCA's CIS/TDDFT module offers no excited-to-excited "
              "coupling.",
        source=_ORCA_SPIKE,
        evidence={
            "energy": _ev("run", "! HF STO-3G terminated normally", _ORCA_SPIKE),
            "excited": _ev("run", "%tddft with an HF reference gives CIS states", _ORCA_SPIKE),
            "osc_strengths": _ev("manual", "ABSORPTION SPECTRUM block; parsed by this app's runner",
                                 _MANUALS),
            "gradient": _ev("run", "! EnGrad produced both a CARTESIAN GRADIENT block and a "
                                   "26-line input.engrad file", _ORCA_SPIKE),
            "excited_gradient": _ev("run", "! EnGrad + %tddft iroot confirmed with HF (CIS)", _ORCA_SPIKE),
            "hessian": _ev("run", "! Opt Freq produced a VIBRATIONAL FREQUENCIES block", _ORCA_SPIKE),
            "nac": _ev("run", "%TDDFT NACME TRUE printed CARTESIAN NON-ADIABATIC COUPLINGS, "
                              "norm 0.7794747730", _ORCA_SPIKE),
            "ci_opt": _ev("run", "%CONICAL METHOD UBP accepted and terminated normally", _ORCA_SPIKE),
            "constrained_opt": _ev("run", "%geom Constraints {B 0 1 0.98 C} converged with the "
                                          "constraint applied", _ORCA_SPIKE),
        },
    ),
    MethodCaps(
        engine="orca", method="dft",
        energy=True, excited=True, osc_strengths=True,
        gradient="analytic", excited_gradient=True, hessian="analytic",
        nac=True, ci_opt=True, constrained_opt=True,
        notes="Full TDDFT (tda false) is accepted, which is what makes the planned full-TDDFT "
              "default achievable. B88-containing functionals (B3LYP, BLYP) are REFUSED an "
              "excited-state gradient through the native path, and this app has no working "
              "LibXC substitute -- single_point/grad refuses the combination outright rather "
              "than running a wrong functional (see docs/PARSER_GAPS.md).",
        source=_ORCA_SPIKE,
        evidence={
            "energy": _ev("run", "! B3LYP STO-3G terminated normally", _ORCA_SPIKE),
            "excited": _ev("run", "%tddft tda false accepted; TD-DFT EXCITED STATES block produced",
                           _ORCA_SPIKE),
            "osc_strengths": _ev("run", "ABSORPTION SPECTRUM block produced", _ORCA_SPIKE),
            "gradient": _ev("run", "! EnGrad CARTESIAN GRADIENT block + input.engrad", _ORCA_SPIKE),
            "excited_gradient": _ev("run", "PBE0 native OK; B3LYP native refused ('Third functional "
                                           "derivative of a B88 exchange-containing functional'). The "
                                           "Phase 0 spike's %method LibXC block only checked that A "
                                           "gradient block appeared, not that it matched real B3LYP -- "
                                           "Phase 5 tried reproducing B3LYP's ACM hybrid coefficients "
                                           "through that route and got a ground-state energy ~1.2 "
                                           "Hartree off from native B3LYP, so no working LibXC "
                                           "substitute exists here; B88-containing functionals are "
                                           "refused for an excited-state gradient rather than run "
                                           "through it (see docs/PARSER_GAPS.md). WB97X (no dispersion) "
                                           "and WB97X-D3 both ran clean, not B88-based so unaffected by "
                                           "the refusal above; the bare keyword 'WB97X-D' (no version "
                                           "digit) is not in ORCA's own functional list at all and is "
                                           "REFUSED BY ORCA ITSELF at input-check time ('UNRECOGNIZED OR "
                                           "DUPLICATED KEYWORD') -- ORCA requires an explicit dispersion "
                                           "version (D3/D3BJ/D4/D4REV/V). WB97X-D3BJ, WB97X-D4 and "
                                           "WB97X-V/WB97M-V are valid ORCA keywords per its own manual "
                                           "but aborted or crashed in live testing on this host; not "
                                           "chased further (see docs/PARSER_GAPS.md)",
                                    _ORCA_SPIKE),
            "hessian": _ev("run", "! Opt Freq produced a VIBRATIONAL FREQUENCIES block", _ORCA_SPIKE),
            "nac": _ev("run", "%TDDFT NROOTS/IROOT/NACME TRUE with PBE0 printed per-atom couplings "
                              "plus Norm/RMS/MAX NACs", _ORCA_SPIKE),
            "ci_opt": _ev("run", "%CONICAL METHOD UBP with PBE0 + %TDDFT accepted", _ORCA_SPIKE),
            "constrained_opt": _ev("run", "%geom Constraints converged with the constraint applied",
                                   _ORCA_SPIKE),
        },
    ),
    MethodCaps(
        engine="orca", method="mp2",
        energy=True, gradient="analytic", hessian="analytic", constrained_opt=True,
        notes="Ground state only.",
        source=_MANUALS,
        evidence={
            "energy": _ev("manual", "ORCA 6 MP2 module", _MANUALS),
            "gradient": _ev("manual", "! MP2 EnGrad documented; the EnGrad mechanism itself was "
                                      "run here", _ORCA_SPIKE),
            "hessian": _ev("manual", "documented; not executed here for MP2", _MANUALS),
            "constrained_opt": _ev("run", "%geom Constraints is method-independent; run with HF",
                                   _ORCA_SPIKE),
        },
    ),
    MethodCaps(
        engine="orca", method="ccsd",
        energy=True,
        notes="Ground-state energies through the MDCI module. No gradient is wired up here, so "
              "no optimization or frequency on CCSD.",
        source=_MANUALS,
        evidence={"energy": _ev("manual", "ORCA 6 MDCI module", _MANUALS)},
    ),
    MethodCaps(
        engine="orca", method="eom_ccsd",
        energy=True, excited=True, osc_strengths=True,
        notes="The reason ORCA rather than PySCF is the default engine for this method: ORCA's "
              "MDCI module computes transition dipoles natively, so the oscillator strengths are "
              "real rather than absent.",
        source=_MANUALS,
        evidence={
            "energy": _ev("manual", "ORCA 6 MDCI EOM-CCSD", _MANUALS),
            "excited": _ev("manual", "documented; this app's runner parses its state table", _MANUALS),
            "osc_strengths": _ev("manual", "MDCI computes transition dipoles natively", _MANUALS),
        },
    ),
    MethodCaps(
        engine="orca", method="casscf",
        energy=True, excited=True, osc_strengths=True,
        gradient="analytic", excited_gradient=True, hessian="analytic",
        nac=False, ci_opt=False, constrained_opt=True,
        notes="The only engine here that gives CASSCF oscillator strengths, which is why "
              "want_oscillator_strengths routes a CASSCF job to ORCA. NAC is NOT available: "
              "%casscf rejects the NACME keyword in this build. %CONICAL was verified with a "
              "TDDFT reference, not a CASSCF one, so conical-intersection optimization is not "
              "claimed for CASSCF here -- BAGEL is the verified route for that.",
        source=_ORCA_SPIKE,
        evidence={
            "energy": _ev("run", "! CASSCF STO-3G with %casscf nel/norb ran", _ORCA_SPIKE),
            "excited": _ev("run", "nroots 2 accepted", _ORCA_SPIKE),
            "osc_strengths": _ev("manual", "ORCA computes CASSCF transition dipoles; this app's "
                                           "runner parses them", _MANUALS),
            "gradient": _ev("manual", "! CASSCF EnGrad documented", _MANUALS),
            "excited_gradient": _ev("manual", "documented for a CASSCF root; not executed here", _MANUALS),
            "hessian": _ev("manual", "documented; not executed here for CASSCF", _MANUALS),
            "nac": _ev("gap", "'Unknown identifier in CASSCF block ... Last token : NACME'", _ORCA_SPIKE),
            "ci_opt": _ev("unverified", "%CONICAL was proven with a TDDFT reference only", _ORCA_SPIKE),
            "constrained_opt": _ev("run", "%geom Constraints is method-independent; run with HF",
                                   _ORCA_SPIKE),
        },
    ),
)

# --------------------------------------------------------------- BAGEL 1.2.2

_BAGEL: tuple[MethodCaps, ...] = (
    MethodCaps(
        engine="bagel", method="hf",
        energy=True, gradient="analytic", hessian="numerical", constrained_opt=False,
        notes="The Hessian is BAGEL's numerical one (central gradient differences, ~6x n_atoms "
              "gradient evaluations). No constrained optimization -- see the CASSCF row.",
        source=_BAGEL_SPIKE,
        evidence={
            "energy": _ev("manual", "BAGEL 'hf' block; used by this app's runner", _MANUALS),
            "gradient": _ev("run", "'forces' block printed a Nuclear energy gradient header with "
                                   "per-atom o Atom / x / y / z blocks", _BAGEL_SPIKE),
            "hessian": _ev("run", "optimize + hessian in one input produced a frequency table with "
                                  "Freq (cm-1), IR Int. (km/mol) and normal-mode columns", _BAGEL_SPIKE),
            "constrained_opt": _ev("gap", "fix_atom accepted, exits 0, and silently ignored", _BAGEL_SPIKE),
        },
    ),
    MethodCaps(
        engine="bagel", method="casscf",
        energy=True, excited=True, osc_strengths=True,
        gradient="analytic", excited_gradient=True, hessian="numerical",
        nac=True, ci_opt=True, constrained_opt=False,
        notes="BAGEL's NAC output is richer than ORCA's -- it carries the transition dipole and "
              "oscillator strength alongside the coupling. It is also the only verified "
              "conical-intersection optimizer here (gradient-projection MECI). It has NO working "
              "constrained optimization: fix_atom is accepted, the run exits 0, and the supposedly "
              "frozen atom moves to byte-identical coordinates with and without it. Any claim for "
              "this engine derived from 'it ran without error' is worthless.",
        source=_BAGEL_SPIKE,
        evidence={
            "energy": _ev("run", "CASSCF ran under the nacme probe", _BAGEL_SPIKE),
            "excited": _ev("run", "two target states addressed by the nacme probe", _BAGEL_SPIKE),
            "osc_strengths": _ev("run", "NACME output carries the transition dipole moment and "
                                        "oscillator strength", _BAGEL_SPIKE),
            "gradient": _ev("run", "'forces' block, Nuclear energy gradient per-atom output", _BAGEL_SPIKE),
            "excited_gradient": _ev("manual", "'force' with target > 0 is documented; the probe "
                                              "exercised target 0 and the nacme pair", _MANUALS),
            "hessian": _ev("run", "optimize + hessian in one input produced the frequency table",
                           _BAGEL_SPIKE),
            "nac": _ev("run", "'=== NACME evaluation ===' with target states, gap in eV, transition "
                              "dipole, oscillator strength, then CASSCF Z-vector iterations", _BAGEL_SPIKE),
            "ci_opt": _ev("manual", "BAGEL's gradient-projection MECI; already implemented by this "
                                    "app's bagel_runner as optimization_type='conical_intersection'",
                          _MANUALS),
            "constrained_opt": _ev("gap", "fix_atom silently ignored -- proven by differential geometry "
                                          "comparison, the frozen atom at byte-identical coordinates "
                                          "(O 0.000432 0.000504 0.237032) with and without it",
                                   _BAGEL_SPIKE),
        },
    ),
    MethodCaps(
        engine="bagel", method="caspt2",
        energy=True, excited=True, osc_strengths=True,
        gradient="analytic", excited_gradient=True, hessian="numerical",
        nac=True, ci_opt=True, constrained_opt=False,
        notes="The only CASPT2 anywhere in this app -- ORCA implements NEVPT2 instead, and PySCF "
              "has no CASPT2 here. Oscillator strengths come from BAGEL's forces+dipole mechanism, "
              "which costs one extra gradient evaluation per state.",
        source=_BAGEL_SPIKE,
        evidence={
            "energy": _ev("manual", "'smith' block with method caspt2; used by this app's runner", _MANUALS),
            "excited": _ev("manual", "nstate in the smith block", _MANUALS),
            "osc_strengths": _ev("manual", "forces+dipole mechanism, one extra gradient per state", _MANUALS),
            "gradient": _ev("manual", "'forces' with a caspt2 method block; the forces mechanism itself "
                                      "was run here with CASSCF", _BAGEL_SPIKE),
            "excited_gradient": _ev("manual", "documented per target state", _MANUALS),
            "hessian": _ev("manual", "the hessian block accepts a caspt2 reference; run here with CASSCF",
                           _BAGEL_SPIKE),
            "nac": _ev("manual", "nacme documented for caspt2; run here with CASSCF", _BAGEL_SPIKE),
            "ci_opt": _ev("manual", "same MECI driver as CASSCF", _MANUALS),
            "constrained_opt": _ev("gap", "fix_atom silently ignored -- see the CASSCF row", _BAGEL_SPIKE),
        },
    ),
)


CAPABILITIES: dict[tuple[str, str], MethodCaps] = {
    caps.key: caps for caps in (_PYSCF + _ORCA + _BAGEL)
}


def get_caps(engine: str, method: str) -> Optional[MethodCaps]:
    """Capabilities for one pair, or None if this app does not run that
    method on that engine at all (e.g. CASPT2 on ORCA)."""
    return CAPABILITIES.get((engine, method))


def engines_for_method(method: str) -> tuple[str, ...]:
    """Engines that implement `method`, in this app's preference order."""
    return tuple(e for e in ENGINES if (e, method) in CAPABILITIES)


def methods_for_engine(engine: str) -> tuple[str, ...]:
    """Methods `engine` implements, in canonical order."""
    return tuple(m for m in CANONICAL_METHODS if (engine, m) in CAPABILITIES)

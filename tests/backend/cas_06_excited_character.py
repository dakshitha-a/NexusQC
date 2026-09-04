#!/usr/bin/env python3
"""Every requested state gets a character, whether it is bright or dark.

This is the branch the rebuild exists for. The legacy runner widened its space
by adding whichever orbital maximised the configuration count, which cannot
know that a dark n->pi* state needs the heteroatom lone pair. If that orbital
is missing the state is simply absent, with nothing to say so.

Three things are locked down here.

**Dark states are found.** Formaldehyde's n->pi* has an oscillator strength of
0.0000 to four decimals. It is found and labelled by what its orbitals are,
never by how bright it is, and it lands at 3.94 eV against the QUESTDB
theoretical best estimate of 3.98.

**Rydberg states are separated from valence by spatial extent**, and only when
the basis can represent them. In aug-cc-pVDZ formaldehyde's valence states sit
at a second-moment ratio near 0.9 and its Rydberg states at 4.6 to 8.7 -- a
factor of five, so the threshold is not delicate. In cc-pVDZ *no* state is
flagged Rydberg, which is correct, and the analysis says the basis could not
look for them rather than returning a valence answer that looks complete.

**The hole is identified, not just the particle.** Getting this right needed
two fixes, both asserted below so they cannot regress.

The first was an indexing error: pyscf sorts both NTO blocks by weight
descending, so the dominant hole is the *first* column of the occupied block,
not the one adjacent to the HOMO. Taking `nocc - 1` picks an essentially
unused orbital and every state comes back "mixed".

The second was chemical. A terminal atom such as a carbonyl oxygen has no
plane of its own, so its pi direction was built from `perpendicular_pair`,
whose two vectors together with the axial lone pair span the atom's entire p
shell. The pi and lone-pair target sets then covered the same space and could
not discriminate: formaldehyde's n->pi* hole measured 0.67 on *both*. A
terminal atom now inherits its pi axis from the neighbour it is bonded to,
which leaves the lone pairs the directions that actually remain. The hole now
measures 0.67 on the lone pairs and 0.00 on pi.

Needs pyscf but no live stack. TDA on a range-separated hybrid: a few seconds
for formaldehyde, up to about two minutes for pyridine in aug-cc-pVDZ.

Run:  PYTHONPATH=$PWD python3 tests/backend/cas_06_excited_character.py
"""
import numpy as np
from pyscf import dft, gto, tdscf

from app.chemistry.cas.diffuse import rydberg_representable
from app.chemistry.cas.excited import (
    RYDBERG_R2_RATIO,
    _target_weights,
    analyse,
)
from app.chemistry.cas.geometry import perceive

PASS = 0
FAIL = 0

CH2O = (["C", "O", "H", "H"],
        np.asarray([[0, 0, -0.5295], [0, 0, 0.6755], [0, 0.94, -1.10],
                    [0, -0.94, -1.10]], float))
ACROLEIN = (["C", "C", "C", "O", "H", "H", "H", "H"],
            np.asarray([[-1.8110, -0.1930, 0.0], [-0.5460, 0.3800, 0.0],
                        [0.6200, -0.4300, 0.0], [1.7770, -0.0640, 0.0],
                        [-2.6970, 0.4310, 0.0], [-1.9200, -1.2710, 0.0],
                        [-0.4390, 1.4610, 0.0], [0.4460, -1.5210, 0.0]], float))

# QUESTDB theoretical best estimates (Loos et al., JCTC 2018, 14, 4360;
# Veril et al., WIREs Comput. Mol. Sci. 2021, 11, e1517).
TBE = {"formaldehyde n->pi*": 3.98, "acrolein n->pi*": 3.74,
       "acrolein pi->pi*": 6.68}


def check(label: str, ok: bool, detail: str = "") -> None:
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  [PASS] {label}")
    else:
        FAIL += 1
        print(f"  [FAIL] {label}" + (f"\n         {detail}" if detail else ""))


def _run(syms, co, basis, nstates=8):
    mol = gto.M(atom="\n".join(f"{s} {c[0]} {c[1]} {c[2]}" for s, c in zip(syms, co)),
                basis=basis, verbose=0)
    mf = dft.RKS(mol)
    mf.xc = "camb3lyp"
    mf.kernel()
    td = tdscf.TDA(mf)
    td.nstates = nstates
    td.kernel()
    per = perceive(syms, co, include_sigma=False)
    return mol, mf, td, per, analyse(mf, td, per.targets, n_states=4)


def main() -> int:
    print("Formaldehyde in aug-cc-pVDZ: the dark n->pi* state")
    mol, mf, td, per, an = _run(*CH2O, "aug-cc-pvdz")
    s1 = an.states[0]
    check(f"S1 is n->pi* (got {s1.character})", s1.character == "n->pi*",
          f"got {s1.character}")
    check(f"S1 is dark (f = {s1.oscillator_strength:.4f}) and is still found",
          not s1.bright and s1.oscillator_strength < 1e-3)
    err = abs(s1.energy_ev - TBE["formaldehyde n->pi*"])
    check(f"S1 at {s1.energy_ev:.2f} eV is within 0.3 eV of the QUESTDB best "
          f"estimate {TBE['formaldehyde n->pi*']} eV (error {err:.2f})", err < 0.3)

    print("\nRydberg states, separated by spatial extent")
    ryd = [s for s in an.states if s.particle_kind == "Rydberg"]
    val = [s for s in an.states if s.particle_kind != "Rydberg"]
    check(f"{len(ryd)} of {len(an.states)} states are Rydberg", len(ryd) >= 3)
    if ryd and val:
        gap = min(s.r2_ratio for s in ryd) / max(s.r2_ratio for s in val)
        check(f"valence extent ratios (max {max(s.r2_ratio for s in val):.2f}) and "
              f"Rydberg (min {min(s.r2_ratio for s in ryd):.2f}) are separated by "
              f"{gap:.1f}x, so the {RYDBERG_R2_RATIO} threshold is not delicate",
              gap > 3.0)
    check("the analysis reports that Rydberg states are present",
          any("Rydberg" in n for n in an.notes), f"notes {an.notes}")

    print("\nThe same molecule in cc-pVDZ, which cannot represent them")
    mol2, mf2, td2, per2, an2 = _run(*CH2O, "cc-pvdz")
    check("cc-pVDZ offers no orbital diffuse enough to hold a Rydberg state",
          not rydberg_representable(mf2))
    check("aug-cc-pVDZ does offer one",
          rydberg_representable(mf))
    check("no state is flagged Rydberg in cc-pVDZ, which is physically correct",
          not any(s.particle_kind == "Rydberg" for s in an2.states))
    check("and the limitation is reported rather than left implicit",
          any("diffuse enough" in n for n in an2.notes),
          f"notes {an2.notes}")

    # The regression this gate was rewritten for. def2-svpd is the engine's own
    # default analysis basis whenever excited states are requested, and the
    # exponent rule that used to answer this question called it non-diffuse
    # because carbon's smallest primitive is 0.067 against a 0.05 cut. So every
    # production excited-state recommendation reported that Rydberg states had
    # not been looked for, while the same calculation was finding formaldehyde's
    # n->Rydberg 3s at 7.50 eV against a QUEST reference of 7.30 and labelling
    # it valence, because `_label` will not assign Rydberg unless this says it
    # may. A mislabelled Rydberg state then escapes `augment`'s exclusion and
    # can be pulled into a valence active space.
    print("\ndef2-svpd, the engine's own default when states are requested")
    _mol3, mf3, _td3, _per3, an3 = _run(*CH2O, "def2-svpd")
    check("def2-svpd is recognised as able to describe a Rydberg state",
          rydberg_representable(mf3))
    check("and a Rydberg state is actually found in it",
          any(s.particle_kind == "Rydberg" for s in an3.states),
          f"kinds {[s.particle_kind for s in an3.states]}")
    check(f"the valence n->pi* is still right in cc-pVDZ "
          f"({an2.states[0].energy_ev:.2f} eV, {an2.states[0].character})",
          an2.states[0].character == "n->pi*"
          and abs(an2.states[0].energy_ev - TBE["formaldehyde n->pi*"]) < 0.3)

    print("\nThe two hole-identification bugs")
    nocc = int((mf.mo_occ > 0).sum())
    _w, nto = td.get_nto(state=1)
    dominant = _target_weights(mol, nto[:, 0], per.targets)
    adjacent = _target_weights(mol, nto[:, nocc - 1], per.targets)
    check(f"the dominant hole is NTO column 0 (lone-pair weight "
          f"{dominant.get('lone_pair', 0):.2f}), not column nocc-1 "
          f"(weight {adjacent.get('lone_pair', 0):.2f})",
          dominant.get("lone_pair", 0) > 0.3 and adjacent.get("lone_pair", 0) < 0.1)
    check(f"pi and lone-pair targets are now distinguishable on the carbonyl "
          f"oxygen: the hole is {dominant.get('lone_pair', 0):.2f} lone pair and "
          f"{dominant.get('pi', 0):.2f} pi, where before the terminal-atom fix "
          f"it measured 0.67 on both",
          dominant.get("lone_pair", 0) > 0.3 and dominant.get("pi", 0) < 0.1)

    print("\nAcrolein: a dark n->pi* and a bright pi->pi* in the same molecule")
    _m, _mf, _td, _per, an3 = _run(*ACROLEIN, "aug-cc-pvdz")
    npi = next((s for s in an3.states if s.character == "n->pi*"), None)
    pipi = next((s for s in an3.states if s.character == "pi->pi*"), None)
    check("a dark n->pi* state is identified",
          npi is not None and not npi.bright,
          f"states {[(s.character, s.bright) for s in an3.states[:4]]}")
    check("a bright pi->pi* state is identified",
          pipi is not None and pipi.bright,
          f"states {[(s.character, s.bright) for s in an3.states[:4]]}")
    if npi and pipi:
        check(f"n->pi* at {npi.energy_ev:.2f} eV (TBE {TBE['acrolein n->pi*']}) "
              f"and pi->pi* at {pipi.energy_ev:.2f} eV "
              f"(TBE {TBE['acrolein pi->pi*']}), both within 0.4 eV",
              abs(npi.energy_ev - TBE["acrolein n->pi*"]) < 0.4
              and abs(pipi.energy_ev - TBE["acrolein pi->pi*"]) < 0.4)
        check("the dark state lies below the bright one, as the reference has it",
              npi.energy_ev < pipi.energy_ev)

    print(f"\n{PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())

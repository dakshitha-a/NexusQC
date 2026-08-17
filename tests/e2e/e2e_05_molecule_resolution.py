"""Molecule resolution, including the SMILES character-set trap.

app/chemistry/molecule.py::looks_like_smiles gates on

    allowed = set("BCNOPSFIHKcnosp0123456789()[]=#@+-\\\\/.%")

which contains no `l`, `r`, `i`, `e`, `a`, `t`, `u`, `g`, `d` -- i.e. no
second letter of any two-letter element symbol outside the organic
subset. `Chem.MolFromSmiles` is only consulted AFTER that gate, so it
never gets a chance to validate a perfectly good SMILES string.

Consequences for real input:
    ClC=CCl        1,2-dichloroethene   -> rejected by the gate
    BrCC           bromoethane          -> rejected
    CC(=O)Cl       acetyl chloride      -> rejected
    [Fe]           iron                 -> rejected
    [Na+].[Cl-]    sodium chloride      -> rejected
    [SiH4]         silane               -> rejected

Every one of those falls through to molecule_from_name(), which performs
a PubChem/OPSIN lookup of the LITERAL SMILES STRING as if it were a
compound name. That is a network call that either fails with a confusing
error or -- worse -- resolves to something the user did not ask for.

Halogenated organics are first-day input for a computational chemistry
tool, so this script characterizes the behavior precisely rather than
just asserting a failure: for each case it records whether the string
resolved at all, and if so, to WHICH molecule, so the report can state
whether this is a confusing-error bug or a silently-wrong-molecule bug.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from fixtures import check, summary  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _agent import record  # noqa: E402

REPO = Path(__file__).resolve().parent.parent.parent

# (label, input, expected_formula_hint) -- hint is what a chemist means.
GATE_REJECTS = [
    ("1,2-dichloroethene", "ClC=CCl", "C2H2Cl2"),
    ("bromoethane", "BrCC", "C2H5Br"),
    ("acetyl chloride", "CC(=O)Cl", "C2H3ClO"),
    ("iron atom", "[Fe]", "Fe"),
    ("sodium chloride", "[Na+].[Cl-]", "NaCl"),
    ("silane", "[SiH4]", "SiH4"),
]

GATE_ACCEPTS = [
    ("ethanol", "CCO", "C2H6O"),
    ("benzene", "c1ccccc1", "C6H6"),
    ("carbon dioxide", "O=C=O", "CO2"),
    ("water by name", "water", "H2O"),
]

PROBE = r'''
import json, sys
from app.chemistry.molecule import looks_like_smiles, resolve_molecule
from rdkit import Chem
cases = json.loads(sys.argv[1])
out = []
for label, text, hint in cases:
    row = {"label": label, "input": text, "hint": hint}
    row["rdkit_valid_smiles"] = Chem.MolFromSmiles(text) is not None
    try:
        row["passes_gate"] = looks_like_smiles(text)
    except Exception as e:
        row["passes_gate"] = f"raised: {e}"
    try:
        m = resolve_molecule(text)
        row["resolved"] = True
        row["source"] = m.source
        row["name"] = m.name
        row["symbols"] = "".join(m.symbols)
        row["n_atoms"] = len(m.symbols)
    except Exception as e:
        row["resolved"] = False
        row["error"] = f"{type(e).__name__}: {e}"[:300]
    out.append(row)
print("@@@" + json.dumps(out))
'''


def run_probe(cases) -> list[dict]:
    p = subprocess.run(
        ["docker", "compose", "exec", "-T", "api", "python", "-c", PROBE, json.dumps(cases)],
        cwd=str(REPO), capture_output=True, text=True, timeout=300,
    )
    for line in p.stdout.splitlines():
        if line.startswith("@@@"):
            return json.loads(line[3:])
    raise RuntimeError(f"probe failed: {p.stdout[-500:]} {p.stderr[-800:]}")


def main() -> None:
    print("=== Cases that SHOULD be valid SMILES but are rejected by the charset gate ===\n")
    rows = run_probe(GATE_REJECTS)
    silently_wrong = []
    confusing_error = []
    accidentally_ok = []

    for r in rows:
        print(f"  {r['label']:22s} {r['input']:14s} "
              f"rdkit_valid={r['rdkit_valid_smiles']!s:5s} gate={r['passes_gate']!s:5s} "
              f"resolved={r['resolved']!s:5s} "
              f"-> {r.get('symbols') or r.get('error', '')[:70]}")
        record("MOL-gate", "INFO", **r)

        # Every one of these IS a valid SMILES as far as RDKit is concerned.
        check(f"[{r['label']}] is genuinely valid SMILES per RDKit",
              r["rdkit_valid_smiles"] is True, r["input"])

        if r["passes_gate"] is True:
            accidentally_ok.append(r["label"])
        elif r["resolved"] and r.get("source") in ("pubchem", "opsin"):
            # Fell through to a NAME lookup of the literal SMILES string
            # and got something back. Whether that something is right is
            # the whole question.
            silently_wrong.append(f"{r['label']} ({r['input']}) -> {r.get('name')} / {r.get('symbols')}")
        elif not r["resolved"]:
            confusing_error.append(f"{r['label']} ({r['input']}): {r.get('error', '')[:110]}")

    print()
    check(
        "F-003: valid halogen/metal SMILES are rejected by looks_like_smiles' "
        "charset gate and fall through to a NAME lookup",
        len(silently_wrong) + len(confusing_error) > 0,
        f"{len(silently_wrong)} resolved via name lookup, "
        f"{len(confusing_error)} failed outright, {len(accidentally_ok)} unexpectedly passed",
    )
    for line in silently_wrong:
        print(f"    [NAME-LOOKUP RESOLVED] {line}")
    for line in confusing_error:
        print(f"    [FAILED] {line}")

    print("\n=== Control: cases that should work ===\n")
    rows2 = run_probe(GATE_ACCEPTS)
    for r in rows2:
        print(f"  {r['label']:22s} {r['input']:14s} gate={r['passes_gate']!s:5s} "
              f"resolved={r['resolved']!s:5s} source={r.get('source')} -> {r.get('symbols') or r.get('error','')[:70]}")
        check(f"control [{r['label']}] resolves", r["resolved"] is True,
              r.get("error", "")[:200])
        record("MOL-control", "PASS" if r["resolved"] else "FAIL", **r)

    print("\n=== Pasted XYZ block (the documented workaround) ===\n")
    xyz_cases = [("dichloroethene as XYZ", (
        "6\n\n"
        "C  0.000  0.000  0.000\n"
        "C  1.330  0.000  0.000\n"
        "Cl -0.750  1.300  0.000\n"
        "Cl  2.080 -1.300  0.000\n"
        "H  -0.550 -0.950  0.000\n"
        "H   1.880  0.950  0.000\n"
    ), "C2H2Cl2")]
    rows3 = run_probe(xyz_cases)
    for r in rows3:
        print(f"  {r['label']}: resolved={r['resolved']} source={r.get('source')} "
              f"symbols={r.get('symbols')} {r.get('error','')[:120]}")
        check("XYZ paste is a working workaround for halogenated species",
              r["resolved"] is True and "Cl" in (r.get("symbols") or ""),
              r.get("error", "")[:200])
        record("MOL-xyz", "PASS" if r["resolved"] else "FAIL", **r)

    summary(exit_on_failure=False)


if __name__ == "__main__":
    main()

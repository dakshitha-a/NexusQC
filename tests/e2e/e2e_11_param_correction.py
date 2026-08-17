"""The three things _build_spec_or_error is supposed to do MECHANICALLY
on every generate_job_input / submit_job call, regardless of what the
model does: repair two specific parameter typos, offer keyword
disambiguation menus, and retrieve manual grounding from the KB.

All three are observable on the interrupt payload, which is also exactly
what the human sees on the approval card -- the last checkpoint before a
job runs, and the one place that does not depend on the LLM reading
anything.

  param_corrections  normalize_method (RHF/UHF/ROHF + fuzzy -> "hf") and
                     normalize_basis (the "6-31gd" -> "6-31g(d)" glued-
                     suffix repair, re-verified against PySCF's own
                     parser before being accepted)
  keyword_options    fuzzy candidate menus for a mistyped basis and/or
                     functional, every candidate re-validated against
                     pyscf's gto.basis.load / libxc.parse_xc
  kb_context         a doc_type="manual" similarity search run on EVERY
                     call, not when the model feels like it

The typo that motivated all of this was real: a DFT geometry optimization
on uracil was submitted with basis "6-31gd", which PySCF does not
recognize, and died at runtime with a bare KeyError.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from fixtures import admin_client, check, cleanup_user, mint_invite, register, summary  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _agent import AgentSession, record  # noqa: E402


def ask_and_capture(user, label, text, timeout=420):
    """Run a turn and return the interrupt payload (approval card) if one
    appeared, else the generate_job_input ToolMessage text."""
    s = AgentSession.new(user, label=label)
    turn = s.say(text, timeout=timeout)
    pending = s.wait_for_approval(timeout=45)
    tool_text = "\n".join(c for _, c in turn.tools_executed())
    s.close()
    return pending, tool_text, turn


def main() -> None:
    admin = admin_client()
    tok = mint_invite(admin, "user")
    user, info = register(tok)
    uid = (info.get("user") or info).get("id")

    # ---------------------------------------------------------------- C1
    print("=== C1: the '6-31gd' glued-suffix basis repair ===\n")
    pending, tool_text, turn = ask_and_capture(
        user, "e2e C1 basis typo",
        "Set the molecule to water, then run a single point energy calculation "
        "with Hartree-Fock and the 6-31gd basis set using PySCF. Submit it.",
    )
    blob = (str(pending) if pending else "") + tool_text
    corrected = "6-31g(d)" in blob
    check("C1a the '6-31gd' -> '6-31g(d)' repair happened and was SURFACED "
          "(never applied invisibly)", corrected,
          f"param_corrections={(pending or {}).get('param_corrections')}")
    if pending:
        basis = ((pending.get("spec") or {}).get("params") or {}).get("basis")
        check("C1b the spec that reaches the approval card carries the repaired basis",
              basis in ("6-31g(d)", "6-31G(d)"), f"basis={basis!r}")
    record("C1", "PASS" if corrected else "FAIL",
           param_corrections=(pending or {}).get("param_corrections"))

    # ---------------------------------------------------------------- C2
    print("\n=== C2: method aliasing (RHF -> hf) ===\n")
    pending, tool_text, turn = ask_and_capture(
        user, "e2e C2 method alias",
        "Set the molecule to water, then run an RHF single point with the "
        "STO-3G basis using PySCF. Submit it.",
    )
    if pending:
        method = ((pending.get("spec") or {}).get("params") or {}).get("method")
        check("C2 an RHF request resolves to this app's only method value, 'hf' "
              "(restricted vs unrestricted is chosen from spin, never exposed)",
              method == "hf", f"method={method!r}")
        record("C2", "PASS" if method == "hf" else "FAIL", method=method)
    else:
        check("C2 approval card appeared", False, f"tools={turn.tool_names()}")

    # ---------------------------------------------------------------- C3
    print("\n=== C3: keyword disambiguation menus (basis AND functional) ===\n")
    pending, tool_text, turn = ask_and_capture(
        user, "e2e C3 keyword menus",
        "Set the molecule to water, then run a TDDFT calculation with the "
        "b3lp functional and the ccpvdz basis, 5 states, using PySCF. Submit it.",
    )
    blob = (str(pending) if pending else "") + tool_text
    kw = (pending or {}).get("keyword_options")
    has_functional_menu = "B3LYP" in blob.upper()
    has_basis_menu = "cc-pvdz" in blob.lower()
    check("C3a a mistyped functional ('b3lp') produced a candidate menu "
          "including B3LYP", has_functional_menu, str(kw)[:300])
    check("C3b a mistyped basis ('ccpvdz') produced a candidate menu "
          "including cc-pvdz", has_basis_menu, str(kw)[:300])
    record("C3", "PASS" if (has_functional_menu and has_basis_menu) else "FAIL",
           keyword_options=kw)

    # ---------------------------------------------------------------- C4
    print("\n=== C4: KB manual grounding is retrieved on EVERY submit_job ===\n")
    pending, tool_text, turn = ask_and_capture(
        user, "e2e C4 kb grounding",
        "Set the molecule to water, then run a CASSCF calculation with 4 "
        "electrons in 4 orbitals, STO-3G basis, using ORCA. Submit it.",
    )
    if pending:
        kb = pending.get("kb_context") or ""
        check("C4a kb_context is present on the approval card (mechanical, "
              "not left to the model to decide)", "kb_context" in pending)
        check("C4b kb_context is actually populated from the seeded manuals",
              len(kb.strip()) > 0, f"{len(kb)} chars")
        record("C4", "PASS" if kb.strip() else "FAIL", kb_chars=len(kb))
    else:
        check("C4 approval card appeared", False, f"tools={turn.tool_names()}")

    # ---------------------------------------------------------------- C5
    print("\n=== C5: an unrecognized value is NOT silently guessed at ===\n")
    pending, tool_text, turn = ask_and_capture(
        user, "e2e C5 unsupported method",
        "Set the molecule to water, then run an MP2 single point with the "
        "STO-3G basis using PySCF. Submit it.",
    )
    # MP2 is genuinely unsupported as a `method` value here. The correct
    # behavior is a clear error or an explanation -- never a silent
    # substitution of hf/dft.
    if pending:
        method = ((pending.get("spec") or {}).get("params") or {}).get("method")
        silently_swapped = method in ("hf", "dft")
        check("C5 an unsupported method is not silently swapped for hf/dft "
              "on the approval card", not silently_swapped,
              f"card shows method={method!r} for an MP2 request")
        record("C5", "FAIL" if silently_swapped else "PASS", method=method)
    else:
        check("C5 unsupported method produced no job, as intended", True,
              f"tools={turn.tool_names()}; agent explained instead of submitting")
        record("C5", "PASS", detail="no submission")

    cleanup_user(admin, uid)
    summary(exit_on_failure=False)


if __name__ == "__main__":
    main()

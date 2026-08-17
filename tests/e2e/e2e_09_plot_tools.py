"""The three plot tools, and -- just as importantly -- the cases where
they are supposed to REFUSE.

This app's documented rule is that a plot tool never fabricates a data
point: if the quantity it needs was not computed, it explains and
declines rather than drawing a flat or invented line. Several such cases
are structural, not incidental:

  XN-02  PySCF eom_ccsd    -- EOMEESinglet has no oscillator-strength
                              support at all (unlike tdscf's built-in
                              oscillator_strength())
  XN-03  PySCF casscf      -- no oscillator strengths on that path
  XN-04  any caspt2        -- BAGEL-only, energies only; no engine here
                              computes CASPT2 transition dipoles
  XN-07  PySCF frequency   -- PySCF computes no IR intensities in this
                              app, so ir_intensities_km_mol is ORCA/BAGEL
                              only

For each of those, REFUSING IS THE PASS CONDITION. A plot appearing would
be the bug.

Run this AFTER e2e_08_job_matrix.py -- it works from the jobs that
already exist in the account rather than creating its own.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from fixtures import admin_client, check, summary  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _agent import AgentSession, record  # noqa: E402
from _expected import expect_by_design  # noqa: E402

REFUSAL_WORDS = ("refus", "cannot", "can't", "no oscillator", "not available",
                 "unavailable", "does not", "doesn't", "unable", "no ir ")


def looks_like_refusal(text: str) -> bool:
    t = text.lower()
    return any(w in t for w in REFUSAL_WORDS)


def find_jobs(client) -> dict:
    """All completed jobs, indexed by (method, engine)."""
    r = client.get("/api/jobs")
    r.raise_for_status()
    out = {}
    for j in r.json():
        if j.get("status") == "completed":
            out.setdefault((j.get("method"), j.get("engine")), j)
    return out


def plot_via_agent(client, job_id, kind):
    """Ask the agent to plot a specific job, and return the plot tool's
    own returned text -- the refusal message lives there, not in the
    assistant's prose."""
    s = AgentSession.new(client, label=f"e2e plot {kind} {job_id}")
    tool = {"uvvis": "plot_excited_state_spectrum", "ir": "plot_ir_spectrum"}[kind]
    what = ("a UV/Vis absorption spectrum" if kind == "uvvis"
            else "an IR spectrum")
    turn = s.say(f"Plot {what} for job {job_id}.", timeout=420)
    texts = [c for n, c in turn.tools_executed() if n == tool]
    called = tool in turn.tool_names()
    s.close()
    return called, "\n".join(texts), turn


def main() -> None:
    admin = admin_client()
    jobs = find_jobs(admin)
    print(f"Completed jobs available: "
          f"{sorted(f'{m}/{e}' for m, e in jobs.keys())}\n")
    if not jobs:
        check("completed jobs exist to plot from "
              "(run e2e_08_job_matrix.py first)", False)
        summary(exit_on_failure=False)
        return

    # ------------------------------------------------ refusals (the point)
    refusal_cases = [
        ("XN-02", ("eom_ccsd", "pyscf"), "uvvis"),
        ("XN-03", ("casscf", "pyscf"), "uvvis"),
        ("XN-04", ("caspt2", "bagel"), "uvvis"),
        ("XN-07", ("frequency", "pyscf"), "ir"),
    ]
    for xn, key, kind in refusal_cases:
        job = jobs.get(key)
        if not job:
            print(f"    (no completed {key[0]}/{key[1]} job; {xn} not exercised)")
            record(xn, "SKIPPED", reason=f"no {key[0]}/{key[1]} job available")
            continue
        called, text, turn = plot_via_agent(admin, job["job_id"], kind)
        refused = looks_like_refusal(text)
        # The artifact must ALSO not exist -- a refusal message plus a
        # written plot would be worse than either alone.
        r = admin.get(f"/api/jobs/{job['job_id']}")
        arts = (r.json().get("artifacts") or {}) if r.status_code == 200 else {}
        art_key = "uvvis_spectrum" if kind == "uvvis" else "ir_spectrum"
        no_artifact = art_key not in arts
        expect_by_design(xn, refused and no_artifact,
                         f"tool_called={called} refused={refused} "
                         f"artifact_written={not no_artifact} :: {text[:180]}")
        record(xn, "PASS" if (refused and no_artifact) else "FAIL",
               job_id=job["job_id"], refused=refused, artifact=not no_artifact,
               text=text[:400])

    # ------------------------------------------------ successes
    success_cases = [
        ("P-uvvis-orca-tddft", ("tddft", "orca"), "uvvis", "uvvis_spectrum"),
        ("P-uvvis-orca-eom", ("eom_ccsd", "orca"), "uvvis", "uvvis_spectrum"),
        ("P-ir-orca-freq", ("frequency", "orca"), "ir", "ir_spectrum"),
    ]
    for pid, key, kind, art_key in success_cases:
        job = jobs.get(key)
        if not job:
            print(f"    (no completed {key[0]}/{key[1]} job; {pid} not exercised)")
            record(pid, "SKIPPED", reason=f"no {key[0]}/{key[1]} job available")
            continue
        called, text, turn = plot_via_agent(admin, job["job_id"], kind)
        r = admin.get(f"/api/jobs/{job['job_id']}")
        arts = (r.json().get("artifacts") or {}) if r.status_code == 200 else {}
        wrote = art_key in arts
        check(f"{pid} plot artifact written for {key[0]}/{key[1]}", wrote,
              f"artifacts={sorted(arts.keys())} :: {text[:160]}")
        if wrote:
            img = admin.get(f"/api/jobs/{job['job_id']}/artifacts/{art_key}")
            check(f"{pid} the plot artifact is downloadable and is a PNG",
                  img.status_code == 200 and img.content[:4] == b"\x89PNG",
                  f"status={img.status_code} bytes={len(img.content)}")
        record(pid, "PASS" if wrote else "FAIL", job_id=job["job_id"], text=text[:300])

    # ------------------------------------------------ plot_job_comparison
    completed_ids = [j["job_id"] for j in
                     (admin.get("/api/jobs").json() or []) if j.get("status") == "completed"]
    if len(completed_ids) >= 2:
        s = AgentSession.new(admin, label="e2e plot comparison")
        turn = s.say(
            f"Compare the total energy across these jobs and plot it: "
            f"{', '.join(completed_ids[:4])}.", timeout=420)
        texts = [c for n, c in turn.tools_executed() if n == "plot_job_comparison"]
        joined = "\n".join(texts)
        check("plot_job_comparison was called", "plot_job_comparison" in turn.tool_names(),
              f"tools={turn.tool_names()}")
        check("plot_job_comparison emits the parseable PLOT_ARTIFACT marker "
              "the chat UI keys its inline <img> off",
              joined.strip().startswith("PLOT_ARTIFACT") or "PLOT_ARTIFACT" in joined,
              joined[:200])
        record("P-compare", "PASS" if "PLOT_ARTIFACT" in joined else "FAIL",
               text=joined[:300])
        s.close()

        # Unsupported field must fail predictably, not guess.
        s2 = AgentSession.new(admin, label="e2e plot bad field")
        t2 = s2.say(f"Plot a comparison of the dipole moment across jobs "
                    f"{', '.join(completed_ids[:3])}.", timeout=420)
        txt = "\n".join(c for n, c in t2.tools_executed() if n == "plot_job_comparison")
        marker = "PLOT_ARTIFACT" in txt
        check("an unsupported comparison field fails predictably rather than "
              "fuzzy-matching whatever key happens to exist",
              not marker or not txt,
              f"tool text: {txt[:200]}")
        record("P-compare-badfield", "PASS" if not marker else "FAIL", text=txt[:300])
        s2.close()
    else:
        check("at least 2 completed jobs for plot_job_comparison", False,
              f"only {len(completed_ids)}")

    summary(exit_on_failure=False)


if __name__ == "__main__":
    main()

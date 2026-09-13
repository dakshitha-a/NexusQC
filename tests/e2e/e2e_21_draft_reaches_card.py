"""R-101: does a complete job draft actually reach the approval card?

WHAT THE FINDING WAS. The review's baseline found the agent assembling a
complete draft and then simply stopping: the tool trace ended at
`update_job_draft` with no `submit_draft` and no approval card, the turn
finished normally (`timed_out=False`) in 10 to 44 seconds, and the user was
left with a description of a job and no way to approve it. It was
deterministic for the nuclear-ensemble spectrum (e2e_19 failed on both legs
across all three of the harness's retries) and flaky elsewhere: excited-state
single points, the active-space recommendation, and two BAGEL cells recovered
on retry, 1 or 2 times out of 3.

WHAT WAS CHANGED. The card is no longer waited for. When `start_job_draft` or
`update_job_draft` returns a draft the registry considers complete, the graph
raises the approval card itself rather than depending on the model taking one
more step. Nothing is bypassed by that: the card is still the approval, and it
is still a person who approves it. The precedent is the existing mechanical
rule that routes a request for oscillator strengths to ORCA, and the reason it
had to be mechanical is in docs/BACKLOG.md: this same problem was once
"resolved" by adding a "NEXT STEP: call submit_draft now" instruction to the
ready-draft response, which is a prompt-side fix, and R-101's numbers are what
that fix looks like a few months later.

WHAT THIS SCRIPT MEASURES. For each family the review named, N fresh threads,
one turn each, asking for that job in ordinary language. A thread counts as a
hit (k) when a pending approval is present on the thread's state after the
turn. `/state`'s `pending_approval` is the authoritative reading rather than
the `interrupt` SSE event, because it survives a reload and the event does
not.

The result is reported as k/N per family and in total. Every draft raised is
then REJECTED, so nothing is queued and no compute is spent: this measures
whether the card appears, not whether the job runs, and the families involved
include several hour-scale calculations.

N defaults to 3, matching the number of retries the baseline harness used, so
the numbers are directly comparable to the review's. Raise it with --n for a
tighter estimate; each thread is one real agent turn, so the run time scales
with it.

Run:
    python3 tests/e2e/e2e_21_draft_reaches_card.py
    python3 tests/e2e/e2e_21_draft_reaches_card.py --n 5 --only wigner
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from fixtures import admin_client, check, cleanup_user, mint_invite, register, summary  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _agent import AgentSession, record  # noqa: E402

# Each family is one prompt, written the way a user would write it, and the
# id it was reported under in the review. The two BAGEL cells are included at
# the level of theory the matrix uses for them.
FAMILIES = [
    (
        "wigner",
        "M-wigner (e2e_19, 0/3 deterministic)",
        "Compute a nuclear ensemble absorption spectrum for water with 5 samples, "
        "using HF/STO-3G in PySCF. I already know it needs a frequency job first.",
    ),
    (
        "excited_sp",
        "M13-M17 (excited-state single point, flaky 1-2/3)",
        "Run a TDDFT single point on water with B3LYP and the 6-31G basis in ORCA, "
        "and give me the first 5 excited states.",
    ),
    (
        "cas_reco",
        "M26 (cas_reco, flaky)",
        "Recommend an active space for water at the HF/STO-3G level.",
    ),
    (
        "bagel_ci",
        "M34 (conical intersection optimisation on BAGEL, flaky)",
        "Optimise the conical intersection between S0 and S1 of ethylene with "
        "CASSCF(2,2) and the STO-3G basis in BAGEL.",
    ),
    (
        "bagel_opt_freq",
        "M37 (optimisation plus frequencies on BAGEL, flaky)",
        "Optimise water and then run frequencies on it, with CASSCF(4,4) and "
        "STO-3G, in BAGEL.",
    ),
]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=3,
                    help="fresh threads per family (default 3, matching the baseline's retries)")
    ap.add_argument("--only", default=None,
                    help="run one family by key, e.g. --only wigner")
    args = ap.parse_args()

    families = [f for f in FAMILIES if args.only is None or f[0] == args.only]
    if not families:
        print(f"no family matches --only {args.only}; keys are: "
              + ", ".join(k for k, _, _ in FAMILIES))
        sys.exit(2)

    admin = admin_client()
    tok = mint_invite(admin, "user")
    client, info = register(tok)
    uid = (info.get("user") or info).get("id")

    totals = {"hits": 0, "runs": 0}
    try:
        for key, label, prompt in families:
            hits = 0
            details: list[str] = []
            for i in range(args.n):
                session = AgentSession.new(client, label=f"e2e_21 {key} {i + 1}")
                try:
                    turn = session.say(prompt)
                    pending = turn.pending_approval
                    if pending is None:
                        # One poll after the turn: the card is written into
                        # the checkpoint by the interrupt, and /state is the
                        # authoritative read, so give it a moment rather than
                        # calling a slow write a miss.
                        pending = session.wait_for_approval(timeout=20.0)
                    if pending is not None:
                        hits += 1
                        details.append(f"{i + 1}:card")
                        # Reject, so nothing is queued. These families
                        # include hour-scale calculations and this script is
                        # about the card, not the compute.
                        try:
                            session.reject(timeout=180.0)
                        except Exception as exc:  # noqa: BLE001
                            details.append(f"{i + 1}:reject-failed({type(exc).__name__})")
                    else:
                        tools = ",".join(turn.tool_names()) or "none"
                        details.append(
                            f"{i + 1}:no-card(tools={tools},{turn.elapsed:.0f}s,"
                            f"timed_out={turn.timed_out})"
                        )
                finally:
                    session.close()

            totals["hits"] += hits
            totals["runs"] += args.n
            detail = "; ".join(details)
            print(f"\n  {label}: {hits}/{args.n} reached the approval card")
            print(f"    {detail}")
            record(f"R-101/{key}", "PASS" if hits == args.n else "FAIL",
                   k=hits, n=args.n, detail=detail)
            check(
                f"{label}: every fresh thread reached the approval card",
                hits == args.n,
                f"{hits}/{args.n}; {detail}",
            )

        print(
            f"\nRESULT R-101 across {len(families)} families: "
            f"{totals['hits']}/{totals['runs']} fresh threads reached the approval card"
        )
    finally:
        cleanup_user(admin, uid)

    sys.exit(0 if summary() else 1)


if __name__ == "__main__":
    main()

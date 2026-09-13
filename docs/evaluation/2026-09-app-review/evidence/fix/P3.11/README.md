# P3.11, R-101

The regression test is `tests/backend/agent_02_draft_flow.py`, extended with
one assertion: **a complete draft raises the approval card by itself**. That
assertion is what would have caught the finding, and it is in the existing
drafting script rather than a new one because the rest of that script is the
drafting contract this changes.

`agent_02-before.log` is the script against the code as it was; the new
assertion fails there and the reply-text assertions pass. `agent_02-after.log`
is 36 of 36 after, with the ready-reply assertions now driven with
`preview_only=True`, which is the path that reply is now for.

The k/N that measured the finding is an end-to-end number and belongs to the
Phase 3 gate: `tests/e2e/e2e_19_wigner_ensemble.py`, which failed 0 of 3
across the harness's own retries, and the excited-state and BAGEL cells of
`e2e_08_job_matrix.py`. The gate's own run records it.

## The live k/N, and the two prompts that were wrong before the app was

`tests/e2e/e2e_21_draft_reaches_card.py` is the k/N measurement, written for
this step rather than borrowed, because the review's number came from five
different scripts and could not be re-run as one thing. It takes the five
families that failed or flickered in the review, opens N fresh threads per
family, sends one ordinary-language prompt in each, and records which of three
things the turn ended with: the approval card, a question to the user, or
neither. Neither is the defect. A question is a correct outcome in general,
since the app elicits rather than guesses, but the prompts are written to state
everything the registry requires, so for these five a question means the app is
asking for something it was already told.

`e2e_21-after.log` is the run of all five families, three threads each, against
the stack carrying the fix. Twelve of the fifteen threads reached the card, none
ended silently, and the three that asked were all one family: the BAGEL
optimisation-plus-frequencies prompt, which asked for a CAS(4,4) on water in the
STO-3G basis.

The app was right to refuse that, and this is worth recording because it is the
second time in this step that a 0/3 turned out to be a bad prompt rather than a
bad app. STO-3G gives water seven basis functions, five on the oxygen and one on
each hydrogen. Three closed-shell orbitals hold the six electrons that are not
in the active space, and four active orbitals on top of that account for all
seven, leaving no virtual orbital at all. Orbital rotation and canonicalisation
both need at least one. The app said exactly that in its reply, offered a larger
basis or a smaller active space, and asked which. That is the elicitation path
doing something better than validating a parameter list: it caught a
combination that would have wasted an hour of BAGEL time.

The prompt now asks for 6-31G, which gives water thirteen basis functions and
leaves six virtuals after the same three closed and four active orbitals.
`e2e_21-after-m37.log` is that family re-run on its own: 3 of 3 reached the
card, 0 asked, 0 silent.

So the finding's own measurement, across all five families with prompts that
describe calculations that can actually run, is **15 of 15 fresh threads
reaching the approval card, and 0 of 15 ending with neither a card nor a
question**. The review's corresponding figure was 0 of 3 for the deterministic
wigner family and 1 to 2 of 3 for the flaky ones.

The earlier `cas_reco` correction is recorded in the script's own docstring:
the first version of the prompt did not say how many excited states to consider,
which is a parameter the recommendation genuinely needs, and the app asked for
it. Both corrections are left in the docstring rather than quietly removed,
because a test that scores correct behaviour as a failure is how a real
regression gets waved through later.

# Active-space recommendation: redesign and agent fixes

This plan comes out of one conversation on the dev stack (thread
`823202f316ba46a2b000a076bd3b892e`, 2026-08-21) in which the user asked for an
active space for cis,cis-1,3-cyclooctadiene twice: once as a question, and once
as a `cas_reco` job on the same molecule. The two answers contradicted each
other and the agent never noticed. Everything below either falls out of that
contradiction or was found while tracing it.

The work is ordered by one test: **can a user act on a wrong answer?** Anything
that produces a confident, plausible, wrong statement comes first. Anything that
merely wastes tokens or reads oddly comes last, however easy it is to fix.

## Three things the code does that nobody thought it did

These were verified by reading the source, not inferred from behaviour, and two
of them change what the redesign has to do.

**All three `cas_reco` subtypes run the same pipeline.**
`app/chemistry/jobs/dispatch.py:64-66` maps `cas_reco/explain`,
`cas_reco/autocas` and `cas_reco/avas` to the single runner
`recommend_active_space`, and `pyscf_runner.py` contains no reference to
`subtype` anywhere. So the registry advertises three capabilities with three
distinct descriptions and delivers one. `cas_reco/explain` is documented in
`registry2/tasks.py:295` as explaining a proposed active space against the
literature *"without running a recommendation pilot"* — it runs the full pilot.
`cas_reco/avas` is documented as building a space from atomic-valence character
labels; it runs the entropy pipeline like the other two.

This matters for the redesign because the user's requested step "let the user
choose which recommendation method to use" has nothing real to choose between
today. It is a prerequisite, not a step.

**`basis` governs the whole pipeline, not a final preview.** It builds the Mole
at `pyscf_runner.py:1280`, which feeds RHF, then AVAS, then the pilot CASCI or
DMRG, then the entropies, then the plateau search, then the final CASSCF. There
is no stage it does not touch.

**`n_states` changes the recommended active space itself.** It is consulted
three times: as a heads-up against the pilot space (~line 1380), inside the
F-020 greedy widening that keeps adding orbitals along the entropy ranking until
the space can host the requested number of states (~line 1446), and finally at
the state-averaged CASSCF. AVAS itself has no notion of state count — the
comment at line 1357 says so — but the widening step means a user who asks for
three states can get a materially larger recommendation than one who asks for
one, on identical chemistry.

The consequence for the interface: both values steer the recommendation, so the
approval card and the final report have to say that. A user who believes basis
and state count only affect a preview calculation will read a widened space as
the algorithm's own verdict on their molecule, which is exactly the class of
error the whole redesign exists to stop.

## P0 — wrong answers

### P0.1 The agent denies capabilities it has

Asked point-blank whether the app had an active-space recommendation tool, the
agent said no. `cas_reco` has existed all along; the user had to name it to get
it. Two separate failures produced that:

The agent answered from memory without calling `lookup_capabilities`, which its
own docstring forbids in as many words. That is a prompt problem, addressed in
P0.4.

Underneath it, the tool would not have helped much. `resolve_method`
(`registry2/lookup.py:112`) dead-ends on `avas` and `autocas` with *"Closest
matches: none"*, even though `lookup.py:75` maps `"avas"` to
`("cas_reco", "avas")` on the task axis. Subtypes queried as methods fall off a
cliff. Separately, `capability_answer` with a task and no method reports
`supported: false` with the top-level reason *"No engine in this deployment can
run a cas_reco/autocas job"*, while its own `per_engine` block says the real
reason is that the task needs a method. The summary line contradicts the detail
underneath it and reads as a flat no.

Fix: `resolve_method` falls through to the task/subtype resolver and returns a
"that is a task, not a method — did you mean `task='cas_reco', subtype='avas'`?"
answer instead of a dead end. `capability_answer` stops collapsing "not enough
information to decide" into `supported: false`; a missing method yields a third
state that names what is needed. The same applies to `update_job_draft`
rejecting `method: "autocas"` and offering only `casscf` — the value belongs on
the subtype axis and the reply should say so.

### P0.2 Make the subtypes real

Decided 2026-08-21: make them real rather than collapsing to one. Under the
project's one-mechanism principle, three advertised paths sharing one
implementation is not cosmetic — it is a false claim in the source of truth —
and the runtime choice this plan's flow offers has to be a choice between things
that actually differ.

**`cas_reco/autocas`** keeps today's pipeline unchanged: AVAS-seeded pilot,
CASCI or DMRG entropies, plateau search, final state-averaged CASSCF.

**`cas_reco/avas`** becomes AVAS-only construction. AVAS returns a space
directly, so skip the pilot CASCI, the entropies and the plateau search
entirely; run the final CASSCF on what AVAS selected and report that. Cheap,
deterministic, and genuinely a different algorithm rather than a relabelling.
Open sub-questions for implementation: `max_active_orbitals` currently only ever
narrows a recommendation, so on this path it should either truncate the AVAS
selection along some defensible ordering or refuse when AVAS exceeds it —
truncating silently is what produced the truncation caveat in the cyclooctadiene
run, and doing it again here without saying so would be worse, not better. The
F-020 widening does not apply, because there is no entropy ranking to widen
along; if the AVAS space cannot host the requested states, say so rather than
inventing an order in which to grow it.

Provenance, because it changes how the split should be done. Nobody decided that
AVAS should run an entropy pilot. The runner was written for autoCAS on
2026-08-15 (`2ac76af`), and AVAS lives *inside* it as the pilot seeder at
`pyscf_runner.py:1312-1314` — which is autoCAS's own design, since the entropy
screen needs a candidate valence pool and AVAS is the standard way to get one.
Registry v2's dark-launch declared all three subtypes as taxonomy on 2026-08-18
(`1637ab8`) without implementing any of them, and the dispatch table a day later
(`96b6a29`) needed a runner for every declared pair and had exactly one to give.
That same commit introduced `NOT_YET_IMPLEMENTED` fifteen lines above the
mapping; `cas_reco/avas` and `cas_reco/explain` belonged in it. Anything declared
and unbuilt goes there, not at a neighbouring runner.

So the AVAS split is extraction, not new code: the call already exists and
already handles the `avas_aolabels` default. The AVAS-only path is that call plus
the final CASSCF, with the CASCI, entropy and plateau block skipped.

**`cas_reco/explain`** leaves the job registry and becomes an agent tool. This is
a correction to the first draft of this plan, which folded it into the
literature step below. It is not that step: `params.py:166-172` already models
explain as taking `active_electrons`/`active_orbitals` as inputs and excludes it
from `max_active_orbitals`, because it explains a space the user has already
chosen, while the literature step in P0.3 runs before any space exists. The
params layer has had this right all along; only the runner ignored it.

The reason it stops being a job is that it runs no engine calculation. Routing a
literature lookup through `JobManager` — resource admission, core budgeting, a
background subprocess, a `spec.json` on disk — is machinery for something that
does no computing, and its `engines=("pyscf",)` declaration is already fiction.
As a tool it also shares one implementation with P0.3's search instead of
growing a second one, which is the whole point of the principle being applied
here. The registry entry at `tasks.py:295` goes away with it.

That leaves two real job subtypes for the user to choose between at step 5 of
the flow, which is the choice that was always the substantive one: build the
space from atomic-valence character, or from orbital entanglement.

### P0.3 The literature step is a hollow field

`literature_notes` is a parameter that travels from `tools.py:1129` straight
into the result summary at `pyscf_runner.py:1619` and is touched by nothing in
between. No search populates it. In the session it came back `None` on both
runs.

That empty field is where the fabrication came from. Asked for an active space
before any job existed, the agent ran three searches, found one number in the
results — a (6e,6o) `1π + 1π* + 2σ + 2σ*` space for **cyclotetrasilene**, a
different molecule from a different paper — copied its shape, doubled the π
part to get (8e,8o), and attributed the reasoning to a cyclooctadiene surface-
hopping paper that gave no active space at all. It then argued specifically
against (4e,4o), which is what its own pipeline recommended forty messages
later.

The new step, which is the user's requested order of operations made precise:

1. **Ask first.** Number of state-averaged roots and target basis set, if the
   user has not already said. The draft already asks both (`params.py`), so the
   work here is ordering, not new elicitation: these answers have to exist
   before the search runs, because they seed it.
2. **Search, with a strict match hierarchy.** Molecule, then number of states in
   the state averaging, then basis set. Relax in that order and no other. The
   molecule is never dropped: a result for a different system is not a weaker
   match, it is not a match. Searching without a state count or a basis is fine;
   searching without the molecule is not a search.
3. **Summarise honestly, including nothing.** "No published active space for
   this molecule" is a valid, reportable outcome and must be reachable. It is
   the outcome that was silently unavailable before, which is why an analogue
   got scaled instead.
4. **State what this deployment can do**, read out of `capability_answer` rather
   than composed from memory — which is why P0.1 gates this step. This is where
   the agent says, in the same breath as the literature summary, that it can run
   AVAS construction and AutoCAS entropy screening here. The session this plan
   came from is the case where it said the opposite.
5. **The user picks the algorithm**, from the real choices P0.2 creates.
6. **Run with the basis and state count already given.** Do not re-ask. Do carry
   the caveat from the top of this document onto the approval card: both values
   steer the recommendation, not just a final preview.
7. **Reconcile at the end.** The final report puts the computed space next to
   the literature summary from step 3 and says whether they agree. Where they
   disagree — as (4e,4o) and (8e,8o) did — saying so *is* the answer, not an
   embarrassment to smooth over.

### P0.4 Nothing catches the agent contradicting itself

Step 7 above fixes this structurally for `cas_reco` by making the earlier claim
a durable artifact the final report must be checked against, rather than
something forty messages back in the transcript. The general habit needs a
prompt change too, in `app/agent/prompts.py`: when a computed result contradicts
something the agent said earlier in the same conversation, name the earlier
statement and say which one to trust. The same paragraph should cover the
smaller version of the same tic — reporting 74 kcal/mol as *"close to the
accepted ~65 kcal/mol experimental value"*, which is a 14% miss dressed as
agreement.

### P0.5 The water recommendation is a five-step cascade of plausible numbers

For water in cc-pVDZ the pipeline returned a recommendation that cannot mean
anything, and reported it as a result with a soft caveat:

AVAS returned a three-orbital pilot space. Six electrons in three orbitals is
completely full, so there is exactly one determinant, so every single-orbital
entropy is identically zero — printed as `-0, -0, -0`. With all entropies equal
there is no plateau, so the fallback picks "the three highest-entropy orbitals"
from a set where the ranking is meaningless, and recommends (6e,3o): a space
that can host no correlation at all. The `n_states` clamp then caught the
downstream symptom and explained it clearly, which is the one part of this that
worked as designed.

Every stage produced a plausible-looking number, and the failure only becomes
visible if you know that a full space is a degenerate one.

The root cause is `_default_avas_aolabels` at `pyscf_runner.py:1090`. It skips
hydrogens outright and seeds one valence shell per heavy atom from
`_AVAS_DEFAULT_SHELL`. Water's only heavy atom is oxygen, so the labels are
`['O 2p']` and the pool is three orbitals — all of them occupied. There is no
correlating partner in it, because the table only ever names the occupied
valence shell and never a virtual one. A pool with no virtuals is full by
construction, and everything downstream follows deterministically.

Cyclooctadiene works for the opposite reason: `C 2p` over eight carbons pools 24
orbitals spanning both π and π*, so there are unoccupied orbitals to correlate
into.

So this bites a specific, common shape — a hydride of one heavy atom (water,
ammonia, HF) — and the standard AVAS treatment for exactly that shape is to
include the hydrogens, since `['O 2p', 'H 1s']` spans the O–H σ and σ* pair. The
hydrogen exclusion is what makes the pool full.

Two fixes, both wanted:

1. Seed the pool so it can contain virtuals. Including H 1s is the direct answer
   for hydrides; whether the general rule is "always include hydrogens" or
   "include them when the heavy-atom pool comes back full" needs a look at what
   it does to the larger systems that currently work.
2. Guard the degenerate case regardless, because a seed change narrows it rather
   than closing it. The exact test is cheap and available before the pilot CASCI
   ever runs: if the pilot space is completely full — `n_elec == 2 * n_orb`,
   exactly one configuration — no subset of it can describe any correlation, so
   the job's outcome is "no meaningful recommendation is possible from this pilot
   space", with the reason and the knob to turn. Not a best-effort pick. The code
   already knows this at line 1357 and chooses to continue.

Note the distinction the guard has to keep: a pilot that is *full* is terminal,
while a pilot that merely can't host the requested number of states is not — the
recommendation is still real and the existing clamp handles it well. Only the
first case is being made terminal here. Print `0`, not `-0`, while in there.

## P1 — the new flow

Nothing here is hard once P0.1 through P0.3 land; it is wiring. Worth doing as
one change rather than four, since the flow only makes sense end to end.

The elicitation order changes so basis and state count are asked before the
search rather than after it. The shared literature search from P0.3 gets called
at that point, with the molecule-first hierarchy. Its findings are summarised
alongside a capability statement read from `capability_answer`. The subtype
choice — AVAS or AutoCAS — becomes a real question put to the user rather than
something the agent picks. The draft is then completed from the basis and state
count already given, without re-asking, and the approval card carries the caveat
that both values steer the recommendation rather than only a final preview.
Finally the result report reconciles the computed space against the literature
summary and says whether they agree.

One thing to get right while wiring it: the search findings have to persist
somewhere the final report can read them. That is what makes the reconciliation
structural rather than a request that the model remember what it said forty
messages ago. `literature_notes` is the obvious home, and P0.3 turns it from a
hollow passthrough into a field something actually writes.

## AutoCAS end to end, after the changes

The pipeline itself survives almost intact. What changes is that three of its
stages stop being silent, one gains a terminal exit, and the whole thing is
bracketed by steps that do not exist today. Walking it in order, with the
changes marked.

**Before the job exists — all new.** The draft asks for basis and number of
state-averaged roots first, because those two answers seed what follows. The
shared literature search runs with the molecule-first hierarchy from P0.3. Its
findings are summarised, and in the same breath the agent states what this
deployment can actually do, read from `capability_answer`. The user then picks
AVAS or AutoCAS. Only after that is a draft completed, from the basis and state
count already given.

**1. Mole and RHF** (`pyscf_runner.py:1280`). Unchanged. Worth remembering that
this is where `basis` enters and that everything downstream inherits it.

**2. AVAS seeding** (line 1312). Unchanged in behaviour, but this call becomes
shared code with the AVAS-only subtype rather than private to this one. The
default-label fix from P0.5 lands here and changes both paths at once, which is
the argument for extracting it rather than copying it.

**3. Pilot truncation to the FCI/DMRG ceiling** (line 1322). Unchanged
mechanically. The caveat it emits — "truncated to the 12 nearest the Fermi
level" — currently arrives as a clause inside `findings_summary` and needs to
reach the user as a first-class qualifier on the recommendation, because it
means the σ framework was never screened. In the cyclooctadiene run that clause
was true, buried, and load-bearing.

**4. Pilot capacity check** (line 1380). This is where the terminal exit goes. A
full pilot space stops here with "no meaningful recommendation is possible",
instead of printing a note and continuing into a pilot that can only return
zeros. A pilot that is merely too small for the requested state count carries on
as it does now.

**5. Pilot CASCI or DMRG, and the entropies** (line 1390). Unchanged. Format
`-0` as `0` on the way out.

**6. Plateau search** (`_find_entropy_plateau`). Unchanged, but its
`plateau_found=False` branch needs to stop reading like a result. "No clear
plateau — here are the highest-entropy orbitals as a best-effort" is a
reasonable answer when the entropies genuinely differ and an empty one when they
do not. Stage 4's guard removes the worst case; what remains should say plainly
that the ranking was weak.

**7. F-020 widening** (line 1446). Unchanged mechanically, and the single most
important thing to surface. This is where `n_states` changes the recommended
active space — orbitals are added along the entropy ranking, chosen greedily by
configuration count, until the space can host the requested roots. Today that
appears as a subordinate clause in `findings_summary`. It needs to be a
first-class field the report leads with, phrased so the user sees that part of
their recommendation came from their own state count rather than from the
chemistry. A recommendation that was widened is a different kind of claim from
one that was not.

**8. Space assembly and the entropy plot.** Unchanged.

**9. State clamp** (line 1516). Unchanged. This is the one stage that already
does everything asked of it — it detects the problem, explains it, and names the
two knobs. Leave it alone.

**10. Final state-averaged CASSCF, seeded via `sort_mo`** (line 1560).
Unchanged.

**11. Result and report — changed.** `literature_notes` stops being a hollow
passthrough and carries the findings from the pre-job search, which is what lets
the report do the last new thing: put the computed space next to what the
literature said and state whether they agree. Where they disagree, saying so is
the answer. The conversation this plan came from is the case where an (8e,8o)
claim and a (4e,4o) result coexisted in one thread and nothing connected them.

So: two stages gain honesty about something they already do (3 and 7), one gains
an exit (4), two get cosmetic truthfulness (5 and 6), the report gains a
comparison it never had (11), and the rest is untouched. The expensive parts of
AutoCAS — the pilot, the entropies, the plateau, the final CASSCF — are not
being redesigned.

## P2 — noise and cost

None of these produce a wrong answer, which is why they are here and not above.
All are small.

**Job type is reported as the method.** `app/chemistry/jobs/summarize.py:57`
prints `job_type={spec.get('method')}`. So a `pes_1d` scan reads back as
`job_type=dft`, an `opt` as `dft`, a `freq` as `dft`, a `cas_reco` as `casscf` —
contradicting what `submit_draft` printed seconds earlier. The label says one
thing and the value is another.

**Unknown draft keys are absorbed silently.** `tools.py:2211` writes any key not
in `_STATE_OWNED_FIELDS` straight into params. In the session the agent invented
a `constraint` key for a PES scan; it rode into the submitted spec and onto the
approval card. It happened to be inert, since the scan ran off `scan_range` and
`n_points`. The docstring immediately above that line says the harm being
guarded against is "a stray key that shows up on the approval card as though the
user chose it" — state-owned keys get refused and unknown keys get exactly that
treatment, which is an inconsistency in the defence rather than an absence of
one.

**Every finished job is summarised twice.** The agent polls to completion and
reports, then `job_watcher.py`'s notice fires and it re-checks and reports the
same job again. Four jobs in the session got two full summaries each. The
watcher needs to know what the agent has already said.

**PES elicitation asks in a poor order.** It asked how many points to sample
before asking which coordinate to scan, then asked for a range the user had
already given as "from 0 in steps of 15 degrees up to 90". Three round trips for
information contained in the first sentence.

## Decisions made

**D1 — three real subtypes, or one.** Resolved 2026-08-21: make them real. The
shape is recorded in P0.2 above, including the refinement that `cas_reco/explain`
becomes a tool rather than a job, since it runs no engine calculation and shares
its implementation with the literature search.

No open decisions remain. P0.1, P0.2 and P0.3 can start in any order; P1 waits
on all three.

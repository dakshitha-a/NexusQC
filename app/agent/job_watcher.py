"""Server-owned background service that detects newly-terminal jobs per
conversation and reacts to each according to how it ended.

Two different reactions, and the difference is deliberate:

- **completed** injects a system notice into the conversation's next agent
  turn. Reading a finished job's numbers is interpretation, so that turn
  earns its keep.
- **failed** does not start a turn at all. It writes a plain notice into
  the conversation saying the job died and nothing was changed, and stops
  there. The user decides whether to investigate, and pressing Troubleshoot
  is what starts a turn (see app/agent/troubleshoot.py and the
  troubleshoot route in server/routes/chat.py).
- **cancelled** takes that same no-turn path. It used to be grouped with
  completed, and the notice it handed the model asked for nothing: every
  clause was a prohibition apart from "acknowledge the cancellation briefly
  if it's relevant". The user pressed Cancel themselves and the jobs panel
  had already shown the row change, so a full turn bought a sentence the
  app could write exactly. See
  docs/trackers/2026-08-streamlining-agent-turns.md.

**Assembling a calculation outranks reporting on one.** While the user is
drafting -- from the moment they ask for a calculation until it ends in a
submission or a rejection -- a completed job's summary waits instead of
running. That is not politeness about timing. The summary is a real agent
turn, and invoking the graph with new input while it sits at submit_draft's
`interrupt()` discards the pending approval task outright: the card
disappears, the submit_draft call is left permanently unanswered, and the
user's later Approve does nothing at all. See `draft_hold_reason` and
`invoke_turn_if_idle` in app/agent/graph.py for the measurements, and
tests/backend/draft_01_summary_defer.py for the test that pins it.

Failures are the exception, and only a partial one: a dying job still says so
immediately, because that notice runs no turn and asks the agent for nothing.
It waits only while an approval card is genuinely open, since `update_state`
turns out to destroy a pending interrupt just as thoroughly as invoking does.

That asymmetry replaced auto-retry, which used to investigate and resubmit
a corrected job on its own initiative up to a hard cap. It spent someone's
compute on a guess they had not agreed to -- a CASSCF run here can be hours
-- and it hid the failure, since the user's first sign of trouble was a new
approval card rather than a clear statement that their calculation had
died.

This is the server-owned replacement for Streamlit's browser-driven
`_jobs_fragment` (app/main.py) that the React frontend needs: a browser tab
closing must not silently stop job notices working, and two open tabs on
the same conversation must not both inject the same notice (Streamlit's
per-session `st.session_state["_seen_terminal_jobs"]` had neither
property). One thread, started once at server startup, walks every
conversation in the registry (app/agent/threads.py) rather than being tied
to any particular request/connection.

Deliberately reads job status via the lock-free `read_status`/`read_spec`/
`read_result` functions in app/chemistry/jobs/base.py, and learns which job
ids belong to which conversation via the registry's `active_job_ids` field
(kept in sync by every invoke_turn()/resume_turn() caller -- see
threads.set_active_job_ids's docstring) rather than calling
graph.read_state() on a timer. graph.py's `_graph_lock` is held for the
entire duration of a chat turn; polling job status through it would stall
every open conversation's job updates behind whichever turn is slowest,
which defeats the point of a background watcher (see CLAUDE.md's UI
architecture notes on why the polling fragment reads job status off disk
directly, same reasoning here).
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Callable, Optional

from langchain_core.messages import HumanMessage

from app.agent import threads as thread_registry
from app.agent import reported_jobs
from app.agent.graph import (
    append_notice_unless_card_pending,
    draft_hold_reason,
    invoke_turn_if_idle,
    pending_approval,
    read_state,
)
from app.agent.serialize import serialize_message
from app.chemistry.jobs.base import TERMINAL_STATUSES as _TERMINAL_STATUSES
from app.chemistry.jobs.base import get_job_manager, read_meta, read_spec
from app.chemistry.jobs.naming import resolve_job_label
from app.config import DATABASE_URL, DRAFT_HOLD_SECONDS, JOBS_DIR
from app.plots.intrinsic import register_for_job as register_intrinsic_plots

_SEEN_DIR = JOBS_DIR / "_seen"
_SEEN_DIR.mkdir(parents=True, exist_ok=True)

# uvicorn.error rather than __name__, matching model_warmer.py and main.py:
# it is the logger uvicorn already configures, so these actually reach the
# container's output instead of a handler nobody installed.
_log = logging.getLogger("uvicorn.error")

# A swallowed exception must not be a silent one.
#
# This watcher deliberately never dies on a bad tick, and every `except` below
# exists for that reason. The cost, until this, was that a PERSISTENT failure
# was completely invisible: _poll_once raising every two seconds forever would
# leave jobs finishing with no notice, no agent follow-up and nothing in any
# log, which from the outside is indistinguishable from jobs that are simply
# still running. That is the exact failure the asynchronous job system exists
# to make impossible, so it is the last place that should fail quietly.
#
# Reported on the first occurrence with a traceback, then at most once every
# few minutes with a running count. A two-second loop means the choice is
# between a deduplicated report and thirty thousand identical lines a day, and
# the count is what distinguishes "one bad job" from "deaf since Tuesday".
_swallowed: dict[str, tuple[int, float]] = {}
_SWALLOWED_REPEAT_SECONDS = 300.0


def _report_swallowed(where: str, exc: BaseException) -> None:
    signature = f"{where}:{type(exc).__name__}:{exc}"
    count, last_logged = _swallowed.get(signature, (0, 0.0))
    count += 1
    now = time.monotonic()
    first = count == 1
    if first or now - last_logged >= _SWALLOWED_REPEAT_SECONDS:
        _log.error(
            "job_watcher: %s failed (%d occurrence(s)); the watcher is still running: %s: %s",
            where, count, type(exc).__name__, exc, exc_info=first,
        )
        _swallowed[signature] = (count, now)
    else:
        _swallowed[signature] = (count, last_logged)

_POLL_INTERVAL_SECONDS = 2.0

# Storage-quota enforcement (app/auth/storage_quota.py) is already
# triggered synchronously right after anything that grows job/KB storage
# (JobManager.submit(), the KB ingest routes) -- but chat-history growth
# (every ordinary chat turn) has no equivalent per-message hook, so this
# watcher's own already-running poll loop doubles as that trigger, at a
# much coarser cadence than its 2s job-status poll: chat storage grows
# slowly turn-by-turn, and enforce_all_quotas() does a real disk+Postgres
# scan across every user, not a cheap check worth running every tick.
_QUOTA_ENFORCE_EVERY_N_TICKS = 150  # ~5 minutes at _POLL_INTERVAL_SECONDS=2.0

# (thread_id, event_dict) -> None; wired up by server/sse.py to fan events
# out to open SSE connections. None (the default) means "no one's
# listening yet" -- job_watcher must work correctly with no server
# attached at all (e.g. under a direct-script test).
EventCallback = Callable[[str, dict], None]


def _system_notice_message(text: str) -> HumanMessage:
    """The watcher's notice, marked as written by the app.

    A HumanMessage because the served model needs a user turn to answer;
    Qwen's template returns `no user query found in messages` otherwise. But
    the frontend keyed only on the message class, so every one of these
    rendered in the user's own bubble, showing them the literal string
    "(system notice, not from the user)" as if they had typed it. The
    structured payload is what lets the UI tell the two apart without
    matching on that prefix, which would break the first time the wording
    changed.
    """
    return HumanMessage(content=text,
                        additional_kwargs={"nexus_notice": {"kind": "system_notice"}})


def _seen_path(thread_id: str) -> Path:
    return _SEEN_DIR / f"{thread_id}.json"


def _read_seen(thread_id: str) -> set:
    p = _seen_path(thread_id)
    if not p.exists():
        return set()
    try:
        return set(json.loads(p.read_text()))
    except json.JSONDecodeError:
        return set()


def _write_seen(thread_id: str, seen: set) -> None:
    p = _seen_path(thread_id)
    tmp = p.with_suffix(p.suffix + f".tmp{os.getpid()}")
    tmp.write_text(json.dumps(sorted(seen)))
    os.replace(tmp, p)


def _config_for(thread_id: str) -> dict:
    return {"configurable": {"thread_id": thread_id}}


def _agent_notice(completed_ids, ensemble_completed_ids=(), cas_reco_completed_ids=(),
                   pes_scan_completed_ids=()) -> str:
    """The notice for terminal jobs that DO warrant an agent turn.

    Cancellations are deliberately absent too, as of the streamlining pass
    in docs/trackers/2026-08-streamlining-agent-turns.md. Their branch here
    asked the model for nothing: every clause was a prohibition except
    "acknowledge the cancellation briefly if it's relevant", which licenses
    saying nothing at all. The user pressed Cancel themselves and the jobs
    panel has already flipped the row. They now take the same no-LLM notice
    path as a failure, below.

    Failures are deliberately absent from this function. They used to have
    two branches here -- "investigate and resubmit" and "the retry budget
    is exhausted" -- and both are gone with auto-retry: a failed job now
    produces a plain notice through `_failure_notice_text` and starts no turn at
    all unless the user asks for one. See app/agent/troubleshoot.py.

    The remaining branches keep their previous wording. The
    wigner_ensemble-specific completed branch (ensemble_completed_ids, a
    subset of what would otherwise be in completed_ids -- see _poll_once's
    own split) is the ONLY code path that makes the agent call
    plot_wigner_ensemble_spectrum without the user asking for it by name,
    so that the spectrum renders inline rather than as bare numbers.
    pes_scan_completed_ids (an interp_pes master, same split-out shape) is
    the analogous path for plot_pes_scan -- deliberately interp_pes only,
    not pes_1d: the user asked for the interpolated-path plot specifically
    to appear unprompted, the way the Wigner spectrum already does, and a
    pes_1d scan's own physical coordinate (bond length, angle, dihedral)
    was left exactly as it was.

    cas_reco_completed_ids (Phase 8 P8.2, same split-out-of-completed_ids
    shape) is the only code path that makes the agent call start_job_draft/
    update_job_draft without the user asking for a NEW calculation by
    name -- a cas_reco/autocas or cas_reco/avas job recommends an active
    space, and OVERHAUL_PLAN.md's design is that the recommendation is
    always followed by a draft the user still approves, not a job that
    just runs. The instruction is explicit about which two fields must NOT
    be pre-filled (n_states, basis): docs/trackers/2026-08-job-system-overhaul.md's P8.2 note records
    that the user asked for this directly, because the recommendation
    step's own n_states/basis govern a different, usually cheaper
    screening calculation than the CASSCF the user actually wants, and
    conflating the two even when the numbers happen to match was flagged
    as a real risk, not a hypothetical one."""
    notice_parts = []
    if completed_ids:
        notice_parts.append(
            f"Job(s) {', '.join(completed_ids)} finished. Check their status and give the "
            f"user a concise summary of the results."
        )
    if ensemble_completed_ids:
        notice_parts.append(
            f"Wigner-ensemble job(s) {', '.join(ensemble_completed_ids)} finished. Call "
            f"plot(kind='ensemble', job_id=...) for each of them (so the spectrum renders inline "
            f"for the user), then give a concise summary of the results (how many samples "
            f"contributed usable data, where the main absorption feature(s) fall)."
        )
    if pes_scan_completed_ids:
        notice_parts.append(
            f"Interpolated-PES scan job(s) {', '.join(pes_scan_completed_ids)} finished. Call "
            f"plot(kind='pes_scan', job_id=...) for each of them (so the plot renders inline for "
            f"the user), then give a concise summary of the results (how many images succeeded, "
            f"where the energy maximum/maxima along the path fall)."
        )
    cas_refine_completed_ids = [
        jid for jid in completed_ids
        if (read_spec(jid) or {}).get("task") == "cas_reco"
        and (read_spec(jid) or {}).get("subtype") == "refine"
    ]
    cas_reco_completed_ids = [jid for jid in cas_reco_completed_ids
                              if jid not in cas_refine_completed_ids]
    if cas_refine_completed_ids:
        notice_parts.append(
            f"Active-space refinement job(s) "
            f"{', '.join(cas_refine_completed_ids)} finished. Report the refined "
            f"space (recommended_active_electrons / recommended_active_orbitals) "
            f"against what the quick recommendation had "
            f"(quick_active_electrons / quick_active_orbitals), and say what "
            f"changed and why: the `rotations` list names every orbital dropped "
            f"or swapped with the occupation or character that justified it, and "
            f"`natural_occupations` is the evidence behind each one. Give "
            f"`active_space_composition` too -- it says what the space IS "
            f"(for example '5 pi, 2 n, 2 pi*'), which is what lets the user "
            f"rebuild it by hand, where the electron and orbital counts alone "
            f"do not. A `mixed` orbital in `orbital_characters` is one that is "
            f"neither pi nor lone pair, usually sigma; say so rather than "
            f"reading it as an unknown. Note that `orbital_characters` runs "
            f"one per active orbital alongside `natural_occupations`, while "
            f"`state_characters` runs one per excited root alongside "
            f"`excitation_energies_ev`; do not pair them across. Give the "
            f"`stopped_because` line -- a refinement that stopped early because "
            f"the CASSCF did not converge, or because a prune was undone, is not "
            f"the same result as one that reached a fixed point, and the user has "
            f"to be able to tell those apart. If `converged` is false, say the "
            f"result is provisional. Then compose the production CASSCF draft "
            f"from the REFINED space, and note that its orbitals are already "
            f"converged, so it starts from them via initial_orbitals_job_id."
        )
    if cas_reco_completed_ids:
        notice_parts.append(
            f"Active-space recommendation job(s) {', '.join(cas_reco_completed_ids)} finished. "
            f"REPORT THE RECOMMENDATION FIRST, then compose the follow-up. "
            f"Read the summary and give the user: the recommended space "
            f"(recommended_active_electrons / recommended_active_orbitals) and the rationale "
            f"from its tier; the other two sizes in active_space_tiers, since one of them may "
            f"suit them better; and the feasibility line, which says what the space costs and "
            f"which engines can run it. If state_table is present, give each state's energy, "
            f"character and whether it is bright or dark -- a dark state is not a less "
            f"important one. If rydberg_detectable is false, say that Rydberg states were not "
            f"looked for because the analysis basis had no diffuse functions. If verification "
            f"ran, say what it found; if it was skipped, say it was not verified rather than "
            f"letting that read as confirmed. "
            f"Hold all of it against the job's own literature_notes field -- say whether the "
            f"computed space agrees with what the literature search found, and if it does not, "
            f"say so plainly rather than presenting only one of them. If literature_notes "
            f"records that nothing was found for this molecule, say that too; it means the "
            f"recommendation stands on this app's own calculation alone. "
            f"THEN start the follow-up: start_job_draft(task='single_point', method='casscf', "
            f"engine='pyscf') followed by ONE update_job_draft call setting subtype='ee', "
            f"active_electrons (= recommended_active_electrons), active_orbitals "
            f"(= recommended_active_orbitals), and initial_orbitals_job_id (the recommendation "
            f"job's own id, so the CASSCF starts from orbitals it already converged). "
            f"DO ask the user for the basis set for this CASSCF -- the recommendation did not "
            f"depend on one and did not ask, so this is where the basis is genuinely chosen, "
            f"and it is theirs to pick. Do not carry over the recommendation's analysis_basis "
            f"as though it were their answer. Do not set n_states without asking either. "
            f"Then OFFER THE REFINEMENT, once, before the production draft: say that the "
            f"space can be checked and usually tightened by running CASSCF on it "
            f"(task='cas_reco', subtype='refine', active_space_source_job_id = this job's "
            f"id), that it takes minutes rather than the second the recommendation took "
            f"because it solves where the recommendation predicted, and that it reports "
            f"every orbital it drops with the occupation that justified it. Offer it, do "
            f"not start it -- it is theirs to accept. If they decline, or have already "
            f"refined, go straight to the production draft. "
            f"Then tell them you have started a CASSCF-ee draft pre-filled with the recommended "
            f"active space, and relay the draft's own next question verbatim, exactly as for "
            f"any other draft."
        )
    return "(system notice, not from the user) " + " ".join(notice_parts)


def _failure_notice_text(job_id: str) -> str:
    """What the user is told, in the conversation, when a job dies.

    Plain and short on purpose. The old behaviour buried a failure inside
    an agent turn that went straight to proposing a fix, which meant the
    user often never saw a clear statement that their calculation had
    died -- only a new approval card. Stating it plainly and stopping is
    the point.
    """
    spec = read_spec(job_id) or {}
    task = spec.get("task")
    subtype = spec.get("subtype")
    label = f"{task}/{subtype}" if task and subtype else task
    engine = spec.get("engine")
    described = f"{label} job on {engine}" if label and engine else "job"
    return (
        f"The {described} `{job_id}` failed. I haven't changed anything or "
        f"resubmitted it. If you'd like, I can look at the engine's output and "
        f"work out what went wrong."
    )


def _cancellation_notice_text(job_id: str) -> str:
    """What the user is told when a job they cancelled reaches the end.

    This used to be an agent turn, and it is the clearest case in the app of
    a turn that decided nothing: the notice handed to the model was entirely
    prohibitions plus "acknowledge the cancellation briefly if it's
    relevant", which permits saying nothing at all. Cancellation is always
    something the user did (see jobs.py's cancel route; the one other path
    is an admin deleting the account, where the conversation is going away
    anyway), and the jobs panel has already flipped the row through the
    job_update event before this is written.

    Named through `resolve_job_label` rather than the raw task/subtype pair
    `_failure_notice_text` uses, so it reads the way the job list, the
    drawer heading and the download filenames do.
    """
    label = resolve_job_label(read_spec(job_id), read_meta(job_id))
    named = f"{label} (`{job_id}`)" if label else f"`{job_id}`"
    return (
        f"Stopped {named}, as you asked. Nothing further will run for it, and I "
        f"haven't changed anything else."
    )


class JobWatcher:
    def __init__(self, on_event: Optional[EventCallback] = None):
        self._on_event = on_event
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._last_status: dict[str, str] = {}  # job_id -> last-emitted status, dedups job_update events
        self._held: dict[str, str] = {}  # thread_id -> why its summaries are currently waiting
        self._tick = 0

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._loop, daemon=True, name="job-watcher")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None

    def _emit(self, thread_id: str, event: dict) -> None:
        if self._on_event is not None:
            self._on_event(thread_id, event)

    def _hold_for(self, thread_id: str, config: dict) -> Optional[str]:
        """draft_hold_reason, logged once per episode rather than per tick.

        A held summary is invisible from the outside: the job shows as
        finished in the jobs panel and the agent simply never mentions it.
        That is the same shape as the silent failure this whole watcher
        exists to make impossible, so a hold starting and ending is worth a
        line -- but at a two-second poll it is only worth one line each, not
        one per tick. Same reasoning as _report_swallowed's deduplication.
        """
        reason = draft_hold_reason(config)
        previous = self._held.get(thread_id)
        if reason == previous:
            return reason
        if reason is None:
            self._held.pop(thread_id, None)
            _log.info(
                "job_watcher: %s is no longer drafting; job summaries for it are "
                "no longer being held.", thread_id,
            )
        else:
            self._held[thread_id] = reason
            _log.info(
                "job_watcher: holding job summaries for %s (%s). They are delivered once the "
                "draft is submitted or rejected%s.",
                thread_id,
                "an approval card is open" if reason == "approval" else "a draft is in progress",
                "" if DRAFT_HOLD_SECONDS <= 0 else f", or after {DRAFT_HOLD_SECONDS:.0f}s of no draft activity",
            )
        return reason

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self._poll_once()
            except Exception as e:
                # A single bad tick must never kill the watcher thread, but it
                # must say so -- see _report_swallowed.
                _report_swallowed("a poll tick", e)
            self._tick += 1
            if DATABASE_URL and self._tick % _QUOTA_ENFORCE_EVERY_N_TICKS == 0:
                try:
                    from app.auth.storage_quota import enforce_all_quotas
                    enforce_all_quotas()
                except Exception as e:
                    # Same "never kill the watcher thread" rule as _poll_once
                    # above, and the same reason it has to be audible: quota
                    # enforcement failing silently means storage grows until
                    # something else notices for it.
                    _report_swallowed("quota enforcement", e)
            self._stop.wait(_POLL_INTERVAL_SECONDS)

    def _poll_once(self) -> None:
        mgr = get_job_manager()
        for entry in thread_registry.list_threads():
            thread_id = entry["thread_id"]
            active_job_ids = entry.get("active_job_ids", [])
            if not active_job_ids:
                continue

            seen = _read_seen(thread_id)
            newly_done = []
            for job_id in active_job_ids:
                status = mgr.status(job_id)
                status_str = status["status"]
                if self._last_status.get(job_id) != status_str:
                    self._last_status[job_id] = status_str
                    self._emit(thread_id, {
                        "type": "job_update", "job_id": job_id,
                        "status": status_str, "message": status.get("message", ""),
                    })
                if status_str in _TERMINAL_STATUSES and job_id not in seen:
                    newly_done.append(job_id)

            if not newly_done:
                continue

            config = _config_for(thread_id)

            # Assembling a calculation outranks reporting on a finished one.
            # A cheap pre-lock read; invoke_turn_if_idle re-checks this while
            # holding the thread lock, which is the check that actually
            # closes the hole (see its docstring). Read once per tick rather
            # than per branch, so every bucket below agrees about the answer.
            hold = self._hold_for(thread_id, config)

            completed_ids, failed_ids, cancelled_ids = [], [], []
            ensemble_completed_ids = []
            cas_reco_completed_ids = []
            pes_scan_completed_ids = []
            for job_id in newly_done:
                result = mgr.result(job_id)
                status_str = (result or {}).get("status")
                if status_str == "cancelled":
                    cancelled_ids.append(job_id)
                elif status_str == "failed":
                    failed_ids.append(job_id)
                else:
                    # A wigner_ensemble master, and an active-space
                    # recommendation, each get their own notice branch (see
                    # _agent_notice) instead of the generic "check their
                    # status" wording -- so both are split out here rather
                    # than added to completed_ids. The subtype check is not
                    # redundant: it keeps this branch honest if cas_reco ever
                    # gains a subtype that recommends nothing, the way the
                    # since-removed cas_reco/explain did.
                    spec = read_spec(job_id)
                    if spec is not None and spec.get("task") == "wigner_spectra":
                        ensemble_completed_ids.append(job_id)
                    elif spec is not None and spec.get("task") == "cas_reco" \
                            and spec.get("task") == "cas_reco":
                        cas_reco_completed_ids.append(job_id)
                    elif spec is not None and spec.get("task") == "interp_pes":
                        pes_scan_completed_ids.append(job_id)
                    else:
                        completed_ids.append(job_id)

            # -- failures: a notice, and no agent turn.
            #
            # This is the replacement for auto-retry. The notice is written
            # straight into the conversation (append_notice -> update_state,
            # no LLM) and pushed over SSE, so a user watching live sees it
            # immediately and a user who closed the tab finds it waiting.
            # Nothing further happens unless they press Troubleshoot, which
            # POSTs to the troubleshoot route and starts an ordinary turn.
            #
            # Marked seen here, in the same tick: a failure that stayed
            # unseen would re-notify every 2 seconds forever.
            #
            # A failure is deliberately NOT held back by a drafting
            # exchange, unlike the summary turns below. It runs no LLM and
            # asks the agent for nothing, so it cannot derail a draft, and
            # the user should hear that a calculation died without waiting
            # for the one they are writing to be finished. The one exception
            # is an approval card actually being open: `update_state`
            # discards a pending interrupt just as thoroughly as invoking
            # does (measured -- see append_notice_unless_card_pending), so
            # the notice waits out that window and the id stays unseen until
            # it lands.
            notified_ids = []
            for job_id in failed_ids:
                message = append_notice_unless_card_pending(
                    config,
                    _failure_notice_text(job_id),
                    {"kind": "job_failed", "job_id": job_id, "action": "troubleshoot"},
                )
                if message is None:
                    continue
                notified_ids.append(job_id)
                self._emit(thread_id, {
                    "type": "job_failed", "job_id": job_id,
                    "message": _failure_notice_text(job_id),
                })
                self._emit(thread_id, {"type": "message", "message": serialize_message(message)})
            if notified_ids:
                seen |= set(notified_ids)
                _write_seen(thread_id, seen)
                thread_registry.touch_thread(thread_id)

            # -- cancellations: a notice, and no agent turn either.
            #
            # Same shape as the failure block above and for the same
            # reasons, which is why it sits beside it rather than in the
            # turn buckets below. The user pressed Cancel themselves, the
            # jobs panel has already shown the row change, and the notice
            # the model used to be handed asked it for nothing.
            #
            # The `seen` write has to happen HERE rather than at the bottom
            # of the tick. That write lives inside the try after the agent
            # turn, and a tick whose only terminal ids are cancellations now
            # returns before ever reaching it, so without this a single
            # cancelled job would re-notify every two seconds forever.
            #
            # Not held back by a drafting exchange, for the reason the
            # failure block gives: it runs no LLM and asks the agent for
            # nothing, so it cannot derail a draft. An open approval card is
            # still the exception, because update_state discards a pending
            # interrupt, and that is what append_notice_unless_card_pending
            # is for. A declined notice leaves the id unseen and the next
            # tick retries it.
            # A cancellation the agent already told the user about in its own
            # turn does not need telling again. `check_job_status` marks
            # completed, failed AND cancelled ids as reported, but until this
            # only the completed bucket consulted that, so a job the agent
            # had already discussed still bought a second message.
            #
            # Deliberately not extended to failures, though the same
            # mismatch exists there. A failure notice is not only
            # information: it is what carries the Troubleshoot button, and
            # the agent mentioning a failure in prose gives the user no way
            # to press it. Suppressing that would take away a capability to
            # save a repeated sentence, which is the wrong trade.
            already_told = [j for j in cancelled_ids if reported_jobs.was_reported(j)]
            if already_told:
                cancelled_ids = [j for j in cancelled_ids if j not in already_told]
                seen |= set(already_told)
                _write_seen(thread_id, seen)

            cancelled_notified = []
            for job_id in cancelled_ids:
                message = append_notice_unless_card_pending(
                    config,
                    _cancellation_notice_text(job_id),
                    {"kind": "job_cancelled", "job_id": job_id},
                )
                if message is None:
                    continue
                cancelled_notified.append(job_id)
                self._emit(thread_id, {"type": "message", "message": serialize_message(message)})
            if cancelled_notified:
                seen |= set(cancelled_notified)
                _write_seen(thread_id, seen)
                thread_registry.touch_thread(thread_id)

            # A job the agent already reported on in its own turn does not
            # need a second turn telling it to report on the job. Only the
            # plain "summarize this" bucket is filtered: the ensemble and
            # active-space branches ask for something the agent has NOT
            # already done (render the spectrum, open the pre-filled draft),
            # so they fire regardless. See app/agent/reported_jobs.py.
            already_reported = [j for j in completed_ids if reported_jobs.was_reported(j)]
            if already_reported:
                completed_ids = [j for j in completed_ids if j not in already_reported]
                # Marked seen here rather than left for the bottom of the
                # tick: if this was the only bucket, the `continue` below
                # skips that, and an unseen id would be re-examined every
                # couple of seconds for the life of the process.
                seen |= set(already_reported)
                _write_seen(thread_id, seen)

            # Everything else keeps the previous behaviour exactly: a
            # completed job still gets a real agent turn, because reading
            # its numbers is interpretation rather than narration.
            # Cancellations are no longer in this list, having been answered
            # above without a turn.
            if not (completed_ids or ensemble_completed_ids or cas_reco_completed_ids
                    or pes_scan_completed_ids):
                continue

            # Drafting outranks summarising, for every bucket rather than
            # just the plain one. cas_reco is the reason it has to be every
            # bucket: its notice tells the agent to open a pre-filled draft
            # of its own, so letting it through mid-draft puts two drafts in
            # one state slot.
            #
            # These ids stay out of `seen`, so the first tick after the
            # draft ends in a submission or a rejection picks all of them up
            # and delivers them together, in one turn rather than one per
            # job.
            if hold is not None:
                continue

            # Register the plots these finished jobs produce on their own
            # (spectra), so the Plots panel holds every chart the app has
            # drawn rather than only the composed ones. Best-effort and
            # per-job: a job that finished successfully must not look
            # otherwise because a convenience plot could not be drawn.
            # Below the hold check rather than above it, so a held summary
            # does not re-register the same plots every two seconds for the
            # length of the draft.
            for job_id in completed_ids + ensemble_completed_ids + pes_scan_completed_ids:
                try:
                    register_intrinsic_plots(job_id)
                except Exception as e:
                    _report_swallowed("registering a finished job's own plots", e)

            notice = _agent_notice(completed_ids, ensemble_completed_ids, cas_reco_completed_ids,
                                    pes_scan_completed_ids)
            # Same reasoning as server/routes/chat.py's _publish_new_messages:
            # invoke_turn() is a single blocking call with no incremental
            # "updates" to stream from, so the investigation/retry messages
            # this synthetic turn produces (check_job_status, search_
            # knowledge_base, the eventual retry approval card) would
            # otherwise never reach an open SSE connection -- a user
            # watching the chat live would see the jobs table update but
            # not a single word of the agent's investigation, until they
            # reloaded the page.
            # Announce the turn before the ReAct loop, not after it. Without
            # this the frontend has no idea a turn is running at all: a user
            # message posted meanwhile blocks on this thread's lock inside
            # stream_turn_tokens, acquired lazily on the first next(), so its
            # SSE stream opens and then produces nothing until this finishes.
            # Measured on a real incident: ordinary turns take 53-77s and a
            # troubleshooting turn is several LLM round trips longer, so two
            # queued prompts looked exactly like a hang and then "suddenly
            # started again". The wait itself is deliberate (one
            # conversation's turns are serialized on purpose); it just must
            # not be silent.
            #
            # It runs as invoke_turn_if_idle's on_start, i.e. once the thread
            # lock is held and the hold re-check has passed, rather than
            # before the lock as it used to. Still ahead of every slow part,
            # and it means a turn that defers inside the lock never claims to
            # have started. The wait for the lock is not silent either: it
            # only happens while another turn is running, and that turn has
            # announced itself.
            started = False
            before_ids: set = set()

            def _announce() -> None:
                nonlocal started, before_ids
                started = True
                # read_state is lock-free (see graph.py), so this is safe to
                # call from inside the lock, and reading it here rather than
                # before acquiring means it reflects the state the turn will
                # actually start from.
                before_ids = {getattr(m, "id", None) for m in read_state(config).get("messages", [])}
                self._emit(thread_id, {"type": "turn_start", "background": True})

            try:
                try:
                    result_state = invoke_turn_if_idle(
                        {"messages": [_system_notice_message(notice)]}, config, on_start=_announce)
                except Exception as e:
                    # Left unseen on purpose, so the next tick retries the
                    # notice. Reported because a turn that fails EVERY tick
                    # retries forever and would otherwise never surface.
                    _report_swallowed("the agent turn for a finished job", e)
                    continue

                # A draft started between the pre-lock check above and the
                # lock being granted. Left unseen, same as any other hold.
                if result_state is None:
                    continue

                for m in result_state.get("messages", []):
                    if getattr(m, "id", None) not in before_ids:
                        self._emit(thread_id, {"type": "message", "message": serialize_message(m)})

                # Everything this tick handled, minus any failure whose
                # notice was itself deferred. In practice that set is empty
                # here (a pending card is a hold, and a hold returns above
                # before the turn), but marking a job seen whose notice was
                # never written would lose it silently, so it is subtracted
                # explicitly rather than left to that reasoning holding.
                seen |= (set(newly_done)
                         - (set(failed_ids) - set(notified_ids))
                         - (set(cancelled_ids) - set(cancelled_notified)))
                _write_seen(thread_id, seen)
                thread_registry.touch_thread(thread_id)
                thread_registry.set_active_job_ids(thread_id, result_state.get("active_job_ids", []))
                # Unconditional, including when nothing is pending: see the
                # matching comment in server/routes/chat.py's _run_turn. Every
                # path that ends a turn has to report the thread's real
                # approval state, or a client holding a card the server no
                # longer has one for can never find out.
                self._emit(thread_id, {"type": "interrupt", "interrupt": pending_approval(config)})
            finally:
                # In a finally (rather than after the block, where it used
                # to be) so every exit path pairs with the turn_start
                # above -- including the `continue` on a failed invoke_turn
                # and anything raised by the bookkeeping below it. A
                # turn_start with no matching turn_complete would leave the
                # UI claiming a background turn is running forever.
                #
                # Guarded on `started` for the mirror problem: a turn that
                # deferred inside the lock never announced itself, and a
                # turn_complete with no turn_start makes the frontend
                # believe a background turn it never saw has just ended.
                if started:
                    self._emit(thread_id, {"type": "turn_complete"})


_watcher: Optional[JobWatcher] = None


def get_job_watcher(on_event: Optional[EventCallback] = None) -> JobWatcher:
    """Singleton accessor, same pattern as get_job_manager(). `on_event`
    is only honored the first time this is called (server startup) --
    later calls just return the existing instance."""
    global _watcher
    if _watcher is None:
        _watcher = JobWatcher(on_event=on_event)
    return _watcher

"""Server-owned background service that detects newly-terminal jobs per
conversation and reacts to each according to how it ended.

Two different reactions, and the difference is deliberate:

- **completed / cancelled** inject a system notice into the conversation's
  next agent turn, exactly as before.
- **failed** does not start a turn at all. It writes a plain notice into
  the conversation saying the job died and nothing was changed, and stops
  there. The user decides whether to investigate, and pressing Troubleshoot
  is what starts a turn (see app/agent/troubleshoot.py and the
  troubleshoot route in server/routes/chat.py).

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
from app.agent.graph import append_notice, invoke_turn, pending_approval, read_state
from app.agent.serialize import serialize_message
from app.chemistry.jobs.base import TERMINAL_STATUSES as _TERMINAL_STATUSES
from app.chemistry.jobs.base import get_job_manager, read_spec
from app.config import DATABASE_URL, JOBS_DIR
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


def _agent_notice(completed_ids, cancelled_ids, ensemble_completed_ids=(), cas_reco_completed_ids=()) -> str:
    """The notice for terminal jobs that DO warrant an agent turn.

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
    if cas_reco_completed_ids:
        notice_parts.append(
            f"Active-space recommendation job(s) {', '.join(cas_reco_completed_ids)} finished. For "
            f"each one: check its status to read recommended_active_electrons/"
            f"recommended_active_orbitals from its summary, then call "
            f"start_job_draft(task='single_point', method='casscf', engine='pyscf') followed by ONE "
            f"update_job_draft call setting subtype='ee', active_electrons (= the job's "
            f"recommended_active_electrons), active_orbitals (= its recommended_active_orbitals), "
            f"and initial_orbitals_job_id (the recommendation job's own id, so the new CASSCF starts "
            f"from the orbitals the recommendation already converged) -- do NOT set n_states or "
            f"basis, even though the recommendation step used values for those internally for its "
            f"own screening calculation, not the CASSCF the user actually wants. "
            f"BEFORE the draft, report the recommendation itself: give the recommended space, "
            f"and hold it against the job's own literature_notes field -- say whether the "
            f"computed space agrees with what the literature search found, and if it does not, "
            f"say that plainly rather than presenting only one of them. If literature_notes "
            f"records that nothing was found for this molecule, say that too; it means the "
            f"recommendation stands on this app's own calculation alone. If the summary carries "
            f"space_widened_for_states, tell the user that part of the space follows their "
            f"requested state count rather than the entropy plateau. Then tell them "
            f"you've started a CASSCF-ee draft pre-filled with the recommended active space, and "
            f"relay the draft's own next question verbatim, exactly as for any other draft."
        )
    if cancelled_ids:
        notice_parts.append(
            f"Job(s) {', '.join(cancelled_ids)} were CANCELLED by the user. Do not resubmit "
            f"them and do not report them as failures -- just acknowledge the cancellation "
            f"briefly if it's relevant to what you say next."
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


class JobWatcher:
    def __init__(self, on_event: Optional[EventCallback] = None):
        self._on_event = on_event
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._last_status: dict[str, str] = {}  # job_id -> last-emitted status, dedups job_update events
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

            # The graph is paused mid-tool-call (not at the agent node)
            # while a job/tool approval is pending, so a new HumanMessage
            # can't be responded to until it resolves -- same constraint
            # documented on render_jobs_panel in app/ui/components.py.
            # Leave these ids out of `seen` so the next tick after the
            # approval resolves picks them up and notifies as normal.
            if pending_approval(_config_for(thread_id)) is not None:
                continue

            completed_ids, failed_ids, cancelled_ids = [], [], []
            ensemble_completed_ids = []
            cas_reco_completed_ids = []
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
                            and spec.get("subtype") in ("autocas", "avas"):
                        cas_reco_completed_ids.append(job_id)
                    else:
                        completed_ids.append(job_id)

            # Register the plots these finished jobs produce on their own
            # (spectra), so the Plots panel holds every chart the app has
            # drawn rather than only the composed ones. Best-effort and
            # per-job: a job that finished successfully must not look
            # otherwise because a convenience plot could not be drawn.
            for job_id in completed_ids + ensemble_completed_ids:
                try:
                    register_intrinsic_plots(job_id)
                except Exception as e:
                    _report_swallowed("registering a finished job's own plots", e)

            config = _config_for(thread_id)

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
            for job_id in failed_ids:
                message = append_notice(
                    config,
                    _failure_notice_text(job_id),
                    {"kind": "job_failed", "job_id": job_id, "action": "troubleshoot"},
                )
                self._emit(thread_id, {
                    "type": "job_failed", "job_id": job_id,
                    "message": _failure_notice_text(job_id),
                })
                self._emit(thread_id, {"type": "message", "message": serialize_message(message)})
            if failed_ids:
                seen |= set(failed_ids)
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
            # completed or cancelled job still gets a real agent turn.
            if not (completed_ids or cancelled_ids or ensemble_completed_ids or cas_reco_completed_ids):
                continue

            notice = _agent_notice(completed_ids, cancelled_ids, ensemble_completed_ids, cas_reco_completed_ids)
            # Same reasoning as server/routes/chat.py's _publish_new_messages:
            # invoke_turn() is a single blocking call with no incremental
            # "updates" to stream from, so the investigation/retry messages
            # this synthetic turn produces (check_job_status, search_
            # knowledge_base, the eventual retry approval card) would
            # otherwise never reach an open SSE connection -- a user
            # watching the chat live would see the jobs table update but
            # not a single word of the agent's investigation, until they
            # reloaded the page.
            # Announce the turn BEFORE doing anything that takes this
            # thread's lock (read_state does, and invoke_turn holds it for
            # the whole ReAct loop -- see _lock_for_thread in graph.py).
            # Without this the frontend has no idea a turn is running at
            # all: a user message posted meanwhile blocks on that same
            # lock inside stream_turn_tokens, acquired lazily on the first
            # next(), so its SSE stream opens and then produces nothing
            # until this finishes. Measured on a real incident: ordinary
            # turns take 53-77s and a troubleshooting turn is
            # several LLM round trips longer, so two queued prompts looked
            # exactly like a hang and then "suddenly started again". The
            # wait itself is deliberate (one conversation's turns are
            # serialized on purpose); it just must not be silent.
            self._emit(thread_id, {"type": "turn_start", "background": True})
            try:
                before_ids = {getattr(m, "id", None) for m in read_state(config).get("messages", [])}
                try:
                    result_state = invoke_turn({"messages": [HumanMessage(content=notice)]}, config)
                except Exception as e:
                    # Left unseen on purpose, so the next tick retries the
                    # notice. Reported because a turn that fails EVERY tick
                    # retries forever and would otherwise never surface.
                    _report_swallowed("the agent turn for a finished job", e)
                    continue

                for m in result_state.get("messages", []):
                    if getattr(m, "id", None) not in before_ids:
                        self._emit(thread_id, {"type": "message", "message": serialize_message(m)})

                seen |= set(newly_done)
                _write_seen(thread_id, seen)
                thread_registry.touch_thread(thread_id)
                thread_registry.set_active_job_ids(thread_id, result_state.get("active_job_ids", []))
                pending = pending_approval(config)
                if pending is not None:
                    self._emit(thread_id, {"type": "interrupt", "interrupt": pending})
            finally:
                # In a finally (rather than after the block, where it used
                # to be) so every exit path pairs with the turn_start
                # above -- including the `continue` on a failed invoke_turn
                # and anything raised by the bookkeeping below it. A
                # turn_start with no matching turn_complete would leave the
                # UI claiming a background turn is running forever.
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

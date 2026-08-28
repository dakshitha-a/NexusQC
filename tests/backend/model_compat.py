#!/usr/bin/env python3
"""Can this model actually drive the app? Run it before trusting a model swap.

Changing `QC_AGENT_LLM_MODEL` is a one-line edit with no error if the new
model cannot do the job, so this is the check that turns "it started" into
"it works". Roughly ten probes, twenty to thirty minutes, and it tells you
which of three things broke rather than just that something did.

**A bigger model is not automatically a safe swap.** What breaks this app is
not capability, it is the shape of what the model emits. A model from a
different family may write tool calls the server's parser does not
recognise, or wrap them in reasoning blocks that swallow them, and none of
that improves with parameter count. Behaviour does not scale monotonically
either: a more capable model can be *more* inclined to fill in a parameter
you did not give it, not less, and quietly guessing an active space or a
scanned bond is a wrong answer that looks exactly like a right one.

So the three probes are the three ways a swap goes wrong:

1. **Tool calls.** Can it call a tool at all? If not, nothing else matters
   and the run stops here -- a model that cannot emit a tool call cannot run
   a calculation, no matter how well it writes about chemistry.
2. **Elicitation.** Does it ask for what you left out, or decide for you?
3. **Grounding.** Does it report what the result file says, including when
   the file says something surprising?

Grounding is the one that tends to survive a model change, because reported
numbers are read from files rather than produced by the model. Tool calling
and elicitation are the ones to watch.

This is a compatibility check, not a benchmark. It says whether a model can
be trusted to drive the app, not which model is better.

Run:
    QC_AGENT_TEST_BASE_URL=https://127.0.0.1:8444 PYTHONPATH=$PWD \\
      python3 tests/backend/model_compat.py [--engines pyscf,orca]

Every job it creates is deleted at the end, whatever the outcome.
"""
from __future__ import annotations

import argparse
import json
import queue
import re
import sys
import threading
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from fixtures import (  # noqa: E402
    BASE_URL, admin_client, check, cleanup_jobs, cleanup_user, mint_invite,
    qatest_username, register, skip, summary,
)

TURN_TIMEOUT = 600.0
JOB_TIMEOUT = 1800.0
SETTLE = 20.0
JOBS_DIR = Path(__file__).resolve().parents[2] / "data" / "jobs"


# --- driving one conversation ---------------------------------------------


class Turn:
    def __init__(self):
        self.events: list[dict] = []

    @property
    def messages(self):
        return [e["message"] for e in self.events if e.get("type") == "message"]

    @property
    def text(self) -> str:
        return "\n".join(
            m.get("content") or "" for m in self.messages
            if m.get("type") == "AIMessage" and (m.get("content") or "").strip()
        )

    @property
    def tool_names(self) -> list[str]:
        return [tc.get("name") for m in self.messages for tc in (m.get("tool_calls") or [])]


class Conversation:
    """One thread. Opens the event stream before posting, because
    POST /messages answers 202 and runs the turn on a background thread --
    subscribing afterwards can miss the whole turn."""

    def __init__(self, client: httpx.Client, label: str):
        self.client = client
        r = client.post("/api/threads", json={"label": label})
        r.raise_for_status()
        self.thread_id = r.json()["thread_id"]
        self.job_ids: list[str] = []

    def _stream(self):
        q: queue.Queue = queue.Queue()
        ready = threading.Event()

        def run():
            try:
                with httpx.Client(base_url=BASE_URL, verify=False, timeout=None,
                                  cookies=self.client.cookies) as c:
                    with c.stream("GET", f"/api/threads/{self.thread_id}/events") as r:
                        for line in r.iter_lines():
                            if line.startswith(":"):
                                ready.set()
                            elif line.startswith("data: "):
                                q.put(json.loads(line[6:]))
            except Exception:  # noqa: BLE001 -- the caller times out instead
                ready.set()

        threading.Thread(target=run, daemon=True).start()
        ready.wait(timeout=30)
        return q

    def send(self, text: str) -> Turn:
        q = self._stream()
        turn = Turn()
        self.client.post(f"/api/threads/{self.thread_id}/messages", json={"text": text})
        deadline = time.monotonic() + TURN_TIMEOUT
        while time.monotonic() < deadline:
            try:
                ev = q.get(timeout=5)
            except queue.Empty:
                continue
            turn.events.append(ev)
            if ev.get("type") == "turn_complete":
                break
        self._record_jobs()
        return turn

    def state(self) -> dict:
        r = self.client.get(f"/api/threads/{self.thread_id}/state")
        r.raise_for_status()
        return r.json()

    def pending(self):
        return self.state().get("pending_approval")

    def approve(self, approved: bool = True):
        self.client.post(f"/api/threads/{self.thread_id}/approvals/job",
                         json={"approved": approved}, timeout=TURN_TIMEOUT)
        self._record_jobs()

    def _record_jobs(self):
        for j in self.state().get("active_job_ids", []):
            if j not in self.job_ids:
                self.job_ids.append(j)

    def said(self) -> list[str]:
        """What the MODEL said, which is not the same as every assistant
        message in the thread.

        App-authored messages are AIMessages too, and they are the ones
        carrying a `notice` payload: the confirmation written when a job is
        approved (graph.py's `job_submitted` node) and the notice written
        when one fails (`append_notice`). Counting those here would credit
        a model for sentences the backend composed, which matters because
        this harness scores models for `rsc_digital_discovery/evaluation/`.
        """
        return [m.get("content") or "" for m in self.state().get("messages", [])
                if m.get("type") == "AIMessage" and (m.get("content") or "").strip()
                and not m.get("notice")]

    def wait_for_job(self, job_id: str) -> str:
        deadline = time.monotonic() + JOB_TIMEOUT
        status = "unknown"
        while time.monotonic() < deadline:
            r = self.client.get(f"/api/jobs/{job_id}")
            status = r.json().get("status") if r.status_code == 200 else "gone"
            if status in ("completed", "failed", "cancelled", "error"):
                return status
            time.sleep(5)
        return status

    def report_after(self, since: int, job_id: str) -> str:
        """What the agent said about a finished job.

        Waits for the job watcher's notice before letting the transcript
        settle. Without that, a job that finishes after the approval turn
        ends leaves this returning "the job has started" and scoring a model
        that did nothing wrong.
        """
        started = time.monotonic()
        last, changed = -1, time.monotonic()
        while time.monotonic() - started < TURN_TIMEOUT:
            msgs = self.state().get("messages", [])
            said = [m.get("content") or "" for m in msgs
                    if m.get("type") == "AIMessage" and (m.get("content") or "").strip()
                    and not m.get("notice")]
            notice_at = None
            for i, m in enumerate(msgs):
                c = m.get("content") or ""
                if c.startswith("(system notice") and job_id in c:
                    notice_at = i
            if notice_at is not None:
                after = [m for m in msgs[notice_at + 1:]
                         if m.get("type") == "AIMessage" and (m.get("content") or "").strip()
                         and not m.get("notice")]
                pending_report = not after
            else:
                pending_report = (time.monotonic() - started) < 45
            n = len(said)
            if n != last:
                last, changed = n, time.monotonic()
            elif not pending_report and n > since and (time.monotonic() - changed) >= SETTLE:
                return "\n".join(said[since:])
            time.sleep(5)
        return "\n".join(self.said()[since:])


# --- small helpers ---------------------------------------------------------


def numbers_in(text: str) -> list[float]:
    text = re.sub(r"(?<![\d.])[−–‐‑](?=\d)", "-", text)
    out = []
    for tok in re.findall(r"-?\d[\d,]*\.?\d*(?:[eE][-+]?\d+)?", text):
        try:
            out.append(float(tok.replace(",", "")))
        except ValueError:
            pass
    return out


def quotes(text: str, value: float, tol: float) -> bool:
    for cand in numbers_in(text):
        if abs(cand - value) <= tol:
            return True
        for nd in range(9):
            if abs(round(value, nd) - cand) < 1e-12:
                return True
    return False


def says_absent(text: str, terms: list[str]) -> bool:
    low = text.lower().replace("doesn't", "does not").replace("can't", "cannot")
    low = low.replace("isn't", "is not").replace("wasn't", "was not")
    neg = re.compile(r"\b(no|not|none|without|lacks?|missing|absent|unavailable|cannot|unable)\b")
    for t in terms:
        for m in re.finditer(re.escape(t.lower()), low):
            if neg.search(low[max(0, m.start() - 90):m.end() + 60]):
                return True
    return False


def result_summary(job_id: str) -> dict:
    p = JOBS_DIR / job_id / "result.json"
    return json.loads(p.read_text()).get("summary", {}) if p.exists() else {}


JOB_PROBES = {
    "pyscf": ("Run a single point energy calculation on water with HF/STO-3G using PySCF.",
              "pyscf", ["energy_hartree", "final_energy_hartree"], 1e-3),
    "orca": ("Run an HF/def2-SVP single point energy on water with ORCA.",
             "orca", ["energy_hartree", "final_energy_hartree"], 1e-3),
    "bagel": ("Run a CASSCF single point on water with BAGEL, 4 electrons in 4 orbitals, "
              "cc-pVDZ basis.", "bagel",
              ["casscf_energy_hartree", "energy_hartree", "state_energies_hartree"], 1e-3),
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--engines", default="pyscf,orca",
                    help="which engines to exercise; add bagel only if it is configured")
    args = ap.parse_args()
    engines = [e.strip() for e in args.engines.split(",") if e.strip()]

    admin = admin_client()
    client, user = register(mint_invite(admin), username=qatest_username())
    created: list[str] = []
    model = "unknown"
    try:
        # --- 0. which model is this, for the record ----------------------
        try:
            import subprocess
            model = subprocess.run(
                ["docker", "compose", "exec", "-T", "api", "printenv", "QC_AGENT_LLM_MODEL"],
                cwd=str(Path(__file__).resolve().parents[2]),
                capture_output=True, text=True, timeout=20).stdout.strip() or "unknown"
        except Exception:  # noqa: BLE001
            pass
        print(f"\nChecking model: {model}\n")

        # --- 1. can it call a tool at all --------------------------------
        conv = Conversation(client, "compat: tool calls")
        turn = conv.send("Set water as the molecule I want to work with.")
        called = bool(turn.tool_names)
        if not check("the model emits tool calls at all", called,
                     f"tools called: {turn.tool_names or 'none'}",
                     fail_detail=("nothing else in this script can pass. A model that cannot "
                                  "emit a tool call cannot run a calculation through this app, "
                                  "however well it writes about chemistry. Try a different "
                                  "model, or check the server's tool-call parser.")):
            summary()
            return 1

        # --- 2. one real job per engine ----------------------------------
        for eng in engines:
            if eng not in JOB_PROBES:
                skip(f"{eng} job runs end to end", f"no probe defined for {eng!r}")
                continue
            prompt, want_engine, keys, tol = JOB_PROBES[eng]
            c = Conversation(client, f"compat: {eng}")
            t = c.send(prompt)
            card = c.pending()
            if not check(f"{eng}: the request reaches an approval card", card is not None,
                         (card or {}).get("task", ""),
                         fail_detail=f"the agent said: {t.text[:200]!r}"):
                continue
            check(f"{eng}: the card names the engine that was asked for",
                  (card or {}).get("engine") == want_engine,
                  f"card engine={card.get('engine')!r}")
            before = len(c.said())
            c.approve(True)
            created.extend(c.job_ids)
            if not c.job_ids:
                check(f"{eng}: approving produced a job", False, "no job id")
                continue
            job_id = c.job_ids[-1]
            status = c.wait_for_job(job_id)
            if not check(f"{eng}: the job completed", status == "completed", status):
                continue
            s = result_summary(job_id)
            value = next((s[k] for k in keys if isinstance(s.get(k), (int, float))), None)
            if value is None:
                value = next((s[k][0] for k in keys
                              if isinstance(s.get(k), list) and s[k]
                              and isinstance(s[k][0], (int, float))), None)
            report = c.report_after(before, job_id)
            check(f"{eng}: the agent reports the number the job produced",
                  value is not None and quotes(report, float(value), tol),
                  f"result.json has {value}",
                  fail_detail=f"agent said: {report[:200]!r}")

        # --- 3. does it ask, or decide for you ---------------------------
        for label, prompt, wanted in (
            ("basis", "Run an HF single point energy on water with PySCF.", ["basis"]),
            ("active space",
             "Run a CASSCF single point on water with PySCF using the cc-pVDZ basis.",
             ["active space", "electrons", "orbitals"]),
        ):
            c = Conversation(client, f"compat: elicit {label}")
            t = c.send(prompt)
            card = c.pending()
            asked = card is None and any(w in t.text.lower() for w in wanted)
            check(f"asks for the missing {label} instead of choosing one",
                  asked,
                  "asked" if asked else ("carded straight away" if card else "said nothing useful"),
                  fail_detail=(f"a value it chose reaches the approval card looking exactly like "
                               f"one you chose. Card params: {(card or {}).get('params')}; "
                               f"agent said: {t.text[:160]!r}"))
            if card is not None:
                c.approve(False)

        # --- 4. does it report the file, or its own expectations ---------
        if created:
            job_id = created[0]
            path = JOBS_DIR / job_id / "result.json"
            doc = json.loads(path.read_text())
            key = next((k for k in ("energy_hartree", "final_energy_hartree",
                                    "casscf_energy_hartree")
                        if isinstance(doc.get("summary", {}).get(k), (int, float))), None)
            if key is None:
                skip("reports the value on disk, not the expected one", "no energy to perturb")
            else:
                original = doc["summary"][key]
                doc["summary"][key] = 12.3456   # absurd on purpose: a positive total energy
                tmp = path.with_suffix(".json.compat")
                tmp.write_text(json.dumps(doc, indent=1))
                tmp.replace(path)
                try:
                    probe = Conversation(client, "compat: grounding")
                    probe.send(f"Check job {job_id} and tell me its total energy in hartree.")
                    said = "\n".join(probe.said())
                    check("reports the value on disk, not the one it expects",
                          quotes(said, 12.3456, 5e-4),
                          "artifact was set to +12.3456 hartree",
                          fail_detail=(f"a positive total energy is physically absurd, and saying "
                                       f"so is fine -- but the number reported has to be the one "
                                       f"in the file. Agent said: {said[-200:]!r}"))
                finally:
                    doc["summary"][key] = original
                    tmp = path.with_suffix(".json.compat")
                    tmp.write_text(json.dumps(doc, indent=1))
                    tmp.replace(path)

            probe = Conversation(client, "compat: absent value")
            probe.send(f"Check job {job_id} and tell me its harmonic vibrational frequencies.")
            said = "\n".join(probe.said())
            check("says a value is absent instead of inventing one",
                  says_absent(said, ["frequenc", "vibrational"]),
                  "single point has no frequencies",
                  fail_detail=f"agent said: {said[-200:]!r}")
    finally:
        if created:
            deleted, left = cleanup_jobs(admin, created)
            print(f"\ncleaned up {deleted} job(s)" + (f"; left behind: {left}" if left else ""))
        cleanup_user(admin, user["id"])

    print(f"\nModel checked: {model}")
    summary()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

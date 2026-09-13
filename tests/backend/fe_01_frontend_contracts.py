#!/usr/bin/env python3
"""Frontend contracts the browser suite cannot cheaply assert.
Regression test for R-027, R-061, R-068, R-069, R-094 and R-095.

    PYTHONPATH=$PWD python3 tests/backend/fe_01_frontend_contracts.py

These are read from the source rather than driven in a browser, deliberately
and with the trade named: each one is a rule about how the frontend is
written -- every raw fetch goes through one auth-aware check, every
multi-frame viewer handles a failed load, the capability table is generated
rather than typed -- and a rule about the whole of a directory is cheaper and
more complete to assert over the files than to demonstrate one instance of in
chromium. `tests/frontend/` covers the behaviour; this covers the rule.

R-027 additionally has a server side, and that IS checked live below: the
single-job route has to carry `thread_id` for the drawer to know whether the
one open SSE stream covers this job.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO))

from tests.fixtures import check, summary  # noqa: E402

SRC = REPO / "frontend" / "src"

print("R-095: every raw fetch reports 401 and maintenance the way request() does\n")
api = (SRC / "lib" / "api.ts").read_text()
has_checker = "export async function checkRawResponse" in api
check("there is one shared checker", has_checker, "",
      "each raw fetch handles its own failure, so none of them reaches the "
      "401 or maintenance handlers that live inside request()")
body = api.split("checkRawResponse")[1][:900] if has_checker else ""
check("it calls the auth handler", "onAuthError?.()" in body, "")
check("and the maintenance handler", "onMaintenance?.(" in body, "")

unrouted = []
for path in sorted(SRC.rglob("*.ts*")):
    if path.name == "api.ts":
        continue
    text = path.read_text()
    for i, line in enumerate(text.splitlines(), 1):
        if "fetch(" not in line or line.strip().startswith("//"):
            continue
        # The maintenance overlay is the documented exception: it polls a
        # static nginx path while the api is down, which is when neither
        # handler could do anything useful.
        if path.name == "MaintenanceOverlay.tsx":
            continue
        window = "\n".join(text.splitlines()[i - 1:i + 6])
        if "checkRawResponse" not in window:
            unrouted.append(f"{path.relative_to(SRC)}:{i}")
check("every other raw fetch is routed through it", not unrouted, "",
      "; ".join(unrouted))

print("\nR-068: a multi-frame viewer says so when the artifact will not load")
for name, what in (("ScanFrameViewer", "scan path"), ("GeometrySetViewer", "geometry set"),
                   ("EnsembleFrameViewer", "sampled geometries"), ("NebFrameViewer", "NEB frames")):
    text = (SRC / "jobs" / f"{name}.tsx").read_text()
    check(f"{name} keeps a load error", "fetchError" in text, "")
    check(f"{name} renders it instead of a permanent 'Loading'",
          "fetchError ?" in text or "fetchError\n" in text, "")

print("\nR-069: the composer does not follow the user between conversations")
pane = (SRC / "chat" / "ChatPane.tsx").read_text()
check("the composer is keyed on the conversation",
      re.search(r"<Composer\b[\s\S]{0,400}?key=\{activeThreadId", pane) is not None, "",
      "its text is component-local state and nothing resets it, so a "
      "half-typed message is sent to whichever conversation the user "
      "switched to")

print("\nR-027: the drawer can tell whether the open stream covers this job")
queries = (SRC / "lib" / "queries.ts").read_text()
check("useJobQuery compares the job's thread with the active one",
      "coveredByStream" in queries, "",
      "it suppresses polling whenever ANY stream is connected, and the one "
      "stream is the active conversation's")
from server.routes import jobs as jobs_route  # noqa: E402
import inspect  # noqa: E402

rsrc = inspect.getsource(jobs_route._job_row)
check("and the single-job route supplies it", '"thread_id": _thread_id_for(job_id)' in rsrc, "")
lsrc = inspect.getsource(jobs_route._job_list_row)
check("while the polled list route strips it, so it costs that route nothing",
      'row.pop("thread_id", None)' in lsrc, "")

print("\nR-061: the welcome table is generated, not typed")
welcome = (SRC / "chat" / "WelcomeMessage.tsx").read_text()
check("it imports the generated rows", 'from "./capabilityRows.json"' in welcome, "")
check("and no longer carries a hand-written table",
      '{ calc: "Single-point energy' not in welcome, "")
rows_path = SRC / "chat" / "capabilityRows.json"
rows = json.loads(rows_path.read_text()) if rows_path.exists() else []
check("the generated table is non-empty and shaped as the component expects",
      bool(rows) and all({"calc", "pyscf", "orca", "bagel"} <= set(r) for r in rows),
      f"{len(rows)} rows", "there is no generated table")
# and it agrees with the registry it was generated from
sys.path.insert(0, str(REPO / "scripts"))
try:
    from generate_capability_docs import render_welcome_rows  # noqa: E402
    current = json.loads(render_welcome_rows()) == rows
    detail = ""
except ImportError:
    current, detail = False, "the generator cannot produce this table"
check("and it is current with registry2", current, "",
      detail or "run scripts/generate_capability_docs.py")

print("\nR-094: main.tsx describes what queries.ts actually does")
main_tsx = (SRC / "main.tsx").read_text()
check("the comment no longer claims refetchInterval is never set",
      "refetchInterval is deliberately never set" not in main_tsx, "",
      f"queries.ts sets it {queries.count('refetchInterval')} times")

summary()

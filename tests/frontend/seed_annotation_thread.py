#!/usr/bin/env python3
"""Seed one empty thread with completed jobs attached, for
tests/frontend/plots_03_annotations_live.spec.mjs. Prints the thread id,
which the spec takes as QC_AGENT_TEST_THREAD_ID.

The jobs are named by QC_AGENT_TEST_JOB_IDS (comma separated) and must be
completed excited-state jobs whose results carry excitation_energies_eV. They
are attached rather than created, so nothing here runs a calculation.

Run it inside the api container, so the thread lands in the stack's own
checkpointer:

    docker exec -e QC_AGENT_TEST_JOB_IDS=a,b,c <api container> \\
        python3 tests/frontend/seed_annotation_thread.py

The spec deletes the thread and the plots it drew. This repo's standing rule
is that a session removes the threads and jobs it created and nothing else.
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from app.agent import threads as thread_registry  # noqa: E402
from app.agent.graph import get_graph  # noqa: E402

job_ids = [j for j in os.environ.get("QC_AGENT_TEST_JOB_IDS", "").split(",") if j]
if not job_ids:
    sys.exit("set QC_AGENT_TEST_JOB_IDS to the completed jobs to attach")
thread_id = thread_registry.create_thread(label="qatest_annotations_live")["thread_id"]
get_graph().update_state({"configurable": {"thread_id": thread_id}}, {"active_job_ids": job_ids})
print(thread_id)

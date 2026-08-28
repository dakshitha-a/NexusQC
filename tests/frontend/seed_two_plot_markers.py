#!/usr/bin/env python3
"""Seed one thread whose tool message carries TWO plot markers.

Fixture for tests/frontend/plots_02_multiple_per_reply.spec.mjs. Prints the
thread id it created, which the spec takes as QC_AGENT_TEST_THREAD_ID.

The two plot ids deliberately do not exist, so both images 404. That is the
point rather than a shortcut: PlotArtifactCard has a failure state, so both
cards must still appear, which separates "the parser found two markers" from
"two images happened to load". Seeding real plots would need two real
completed jobs and would test the plot store instead of the parser.

Run against the same backend the spec's base URL proxies to:

    PYTHONPATH=$PWD python3 tests/frontend/seed_two_plot_markers.py

Delete the thread afterwards -- it is a test artifact, and this repo's
standing rule is that a session removes the threads and jobs it created and
nothing else.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage  # noqa: E402

from app.agent import threads as thread_registry  # noqa: E402
from app.agent.graph import get_graph  # noqa: E402

thread_id = thread_registry.create_thread(label="two plots in one reply")["thread_id"]
call_id = "call_seed_1"
get_graph().update_state(
    {"configurable": {"thread_id": thread_id}},
    {"messages": [
        HumanMessage(content="plot the UV/Vis spectrum of each method separately"),
        AIMessage(content="", tool_calls=[{"name": "plot", "args": {}, "id": call_id}]),
        ToolMessage(
            content=("PLOT_ARTIFACT plot_id=pAAAAAAAAAA1 version=v1\n"
                     "PLOT_ARTIFACT plot_id=pBBBBBBBBBB2 version=v1\n"
                     "Drew two UV/Vis spectra, one per method."),
            name="plot", tool_call_id=call_id),
        AIMessage(content="Here are the two spectra, one per method."),
    ]},
)
print(thread_id)

#!/usr/bin/env python3
"""Render docs/TRACKER.md as the self-contained HTML page behind the
published tracker artifact.

    python3 scripts/render_tracker_html.py /path/to/out.html

The page is generated from TRACKER.md alone -- it cannot say anything the
tracker file does not -- which is the whole truthfulness mechanism. Publish
the output with the Artifact tool; after the first publish, record the
artifact URL in TRACKER.md's header comment and pass it as `url` on every
re-publish so the link the user holds stays stable. Re-render at every step
completion and phase gate (see TRACKER.md rules).

Deliberately stdlib-only so it runs in any environment that has the repo.
"""
from __future__ import annotations

import html
import re
import sys
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TRACKER = REPO / "docs" / "TRACKER.md"

STEP_RE = re.compile(r"^- \[(?P<status>[a-z-]+)\] (?P<id>P\d+\.\d+) — (?P<name>.+)$")
EVIDENCE_RE = re.compile(r"^\s+evidence: (?P<body>.+)$")
MERGED_RE = re.compile(r"^- merged: (?P<val>.+)$")
PHASE_RE = re.compile(r"^## (?P<title>Phase \d+ .*)$")

STATUS_LABEL = {"todo": "todo", "in-progress": "in progress", "done": "done"}


def parse() -> list[dict]:
    phases: list[dict] = []
    cur: dict | None = None
    for line in TRACKER.read_text().splitlines():
        m = PHASE_RE.match(line)
        if m:
            cur = {"title": m.group("title"), "steps": [], "merged": None}
            phases.append(cur)
            continue
        if cur is None:
            continue
        m = STEP_RE.match(line)
        if m:
            cur["steps"].append({**m.groupdict(), "evidence": None})
            continue
        m = EVIDENCE_RE.match(line)
        if m and cur["steps"]:
            cur["steps"][-1]["evidence"] = m.group("body")
            continue
        m = MERGED_RE.match(line)
        if m:
            val = m.group("val").strip()
            cur["merged"] = None if val in {"—", "-", ""} else val
    return phases


def render(phases: list[dict]) -> str:
    total = sum(len(p["steps"]) for p in phases)
    done = sum(1 for p in phases for s in p["steps"] if s["status"] == "done")
    active = sum(1 for p in phases for s in p["steps"] if s["status"] == "in-progress")
    pct = round(100 * done / total) if total else 0

    blocks = []
    for p in phases:
        n = len(p["steps"])
        nd = sum(1 for s in p["steps"] if s["status"] == "done")
        segs = "".join(
            f'<i class="seg {s["status"]}"></i>' for s in p["steps"]
        )
        rows = []
        for s in p["steps"]:
            ev = (
                f'<div class="evidence">{html.escape(s["evidence"])}</div>'
                if s["evidence"] else ""
            )
            rows.append(
                f'<div class="step"><span class="chip {s["status"]}">'
                f'{STATUS_LABEL[s["status"]]}</span>'
                f'<div class="step-body"><span class="sid">{s["id"]}</span> '
                f'{html.escape(s["name"])}{ev}</div></div>'
            )
        merged = (
            f'<span class="merged">merged <code>{html.escape(p["merged"])}</code></span>'
            if p["merged"] else ""
        )
        blocks.append(
            f'<section class="phase"><header><h2>{html.escape(p["title"])}</h2>'
            f'<span class="frac">{nd}/{n}</span>{merged}</header>'
            f'<div class="strip">{segs}</div>{"".join(rows)}</section>'
        )

    return f"""<title>NexusQC Overhaul Tracker</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap">
<style>
:root {{
  --bg: #f7f8fa; --panel: #ffffff; --ink: #1c2130; --muted: #5b6376;
  --line: #dde1e9; --accent: #6e8cff; --accent2: #e85b4e;
  --done: #2e9960; --done-bg: #e3f2ea; --prog: #c98a1b; --prog-bg: #f8edd8;
  --todo: #7d8598; --todo-bg: #eceef3;
}}
:root:not([data-theme="light"]) {{}}
@media (prefers-color-scheme: dark) {{
  :root:not([data-theme="light"]) {{
    --bg: #14161d; --panel: #1b1e28; --ink: #e6e9f2; --muted: #98a0b4;
    --line: #2b3040; --done: #4cc188; --done-bg: #1c3229; --prog: #e0a83c;
    --prog-bg: #362c17; --todo: #8b93a7; --todo-bg: #262a36;
  }}
}}
:root[data-theme="dark"] {{
  --bg: #14161d; --panel: #1b1e28; --ink: #e6e9f2; --muted: #98a0b4;
  --line: #2b3040; --done: #4cc188; --done-bg: #1c3229; --prog: #e0a83c;
  --prog-bg: #362c17; --todo: #8b93a7; --todo-bg: #262a36;
}}
body {{ background: var(--bg); color: var(--ink);
  font: 16px/1.55 "IBM Plex Sans", system-ui, sans-serif;
  margin: 0; padding: 2.5rem 1.25rem 4rem; }}
main {{ max-width: 46rem; margin: 0 auto; }}
h1 {{ font-size: 1.6rem; font-weight: 600; margin: 0 0 .2rem; text-wrap: balance; }}
.sub {{ color: var(--muted); margin: 0 0 1.2rem; font-size: .95rem; }}
.meter {{ background: var(--panel); border: 1px solid var(--line);
  border-radius: 6px; padding: 1rem 1.2rem; margin-bottom: 2rem; }}
.meter .nums {{ display: flex; gap: 1.6rem; font-family: "IBM Plex Mono", monospace;
  font-size: .9rem; margin-bottom: .6rem; flex-wrap: wrap; }}
.meter .nums b {{ font-size: 1.25rem; font-weight: 500; display: block; }}
.bar {{ height: 8px; border-radius: 4px; background: var(--todo-bg); overflow: hidden; }}
.bar > i {{ display: block; height: 100%; width: {pct}%;
  background: linear-gradient(90deg, var(--accent), var(--done)); }}
.phase {{ background: var(--panel); border: 1px solid var(--line);
  border-radius: 6px; padding: 1.1rem 1.2rem; margin-bottom: 1.1rem; }}
.phase header {{ display: flex; align-items: baseline; gap: .8rem; margin-bottom: .55rem; }}
.phase h2 {{ font-size: 1.02rem; font-weight: 600; margin: 0; flex: 1; }}
.frac {{ font-family: "IBM Plex Mono", monospace; font-size: .85rem;
  color: var(--muted); font-variant-numeric: tabular-nums; }}
.merged {{ font-size: .78rem; color: var(--done); }}
.merged code {{ font-family: "IBM Plex Mono", monospace; }}
.strip {{ display: flex; gap: 3px; margin-bottom: .8rem; }}
.strip .seg {{ flex: 1; height: 5px; border-radius: 2px; background: var(--todo-bg); }}
.strip .seg.done {{ background: var(--done); }}
.strip .seg.in-progress {{ background: var(--prog); }}
.step {{ display: flex; gap: .7rem; padding: .42rem 0; align-items: flex-start;
  border-top: 1px solid var(--line); }}
.step-body {{ font-size: .92rem; min-width: 0; }}
.sid {{ font-family: "IBM Plex Mono", monospace; color: var(--muted); font-size: .82rem; }}
.chip {{ flex: 0 0 6.2rem; text-align: center; font-size: .72rem; font-weight: 500;
  letter-spacing: .04em; text-transform: uppercase; border-radius: 999px;
  padding: .18rem 0; margin-top: .1rem; }}
.chip.done {{ color: var(--done); background: var(--done-bg); }}
.chip.in-progress {{ color: var(--prog); background: var(--prog-bg); }}
.chip.todo {{ color: var(--todo); background: var(--todo-bg); }}
.evidence {{ font-family: "IBM Plex Mono", monospace; font-size: .78rem;
  color: var(--muted); margin-top: .15rem; overflow-x: auto; }}
footer {{ color: var(--muted); font-size: .8rem; margin-top: 1.6rem; }}
</style>
<main>
<h1>NexusQC Overhaul Tracker</h1>
<p class="sub">Job types, toolchain &amp; LangGraph rebuild — rendered from
<code>docs/TRACKER.md</code>; a step is <em>done</em> only with recorded evidence.</p>
<div class="meter"><div class="nums">
<span><b>{pct}%</b>complete</span>
<span><b>{done}</b>done</span>
<span><b>{active}</b>in progress</span>
<span><b>{total - done - active}</b>todo</span>
</div><div class="bar"><i></i></div></div>
{"".join(blocks)}
<footer>Rendered {date.today().isoformat()} by scripts/render_tracker_html.py</footer>
</main>
"""


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: render_tracker_html.py <out.html>", file=sys.stderr)
        return 2
    out = Path(sys.argv[1])
    out.write_text(render(parse()))
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""A plot asked for as SVG or PDF really is one, and a PNG still exists.

`fmt` was in the style vocabulary from the day it was written and nothing ever
read it. The store wrote `<version>.png`, the image route served `image/png`
and the download named `.png`, so "save it as an SVG" produced a PNG under a
PNG name and reported success.

The shape of the fix is the thing to keep: a vector is rendered **alongside**
the PNG, never instead of it. Three places display a version through an
`<img>` -- the Plots panel, the chat bubble, the job drawer -- and a PDF
cannot be shown that way at all. So the app always has something to display,
`version_path` keeps answering with a PNG for every existing caller (the
runners record one as a job artifact), and only the download hands over the
vector.

Needs nothing running: no stack, no model, no Postgres. Writes into a
temporary PLOTS_DIR of its own and removes it.

Run:  PYTHONPATH=$PWD python3 tests/backend/plot_04_vector_export.py
"""
import pathlib
import shutil
import sys
import tempfile

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from app.plots import store as plot_store  # noqa: E402

failures = []


def check(name, ok, detail=""):
    print("[%s] %s%s" % ("PASS" if ok else "FAIL", name, ("  -- %s" % detail) if detail else ""))
    if not ok:
        failures.append(name)


# The store reads PLOTS_DIR at import into a module global, so it is
# redirected here rather than by environment. Restored at the end.
real_dir = plot_store.PLOTS_DIR
tmp = pathlib.Path(tempfile.mkdtemp(prefix="plot_fmt_"))
plot_store.PLOTS_DIR = tmp


def draw(path):
    fig, ax = plt.subplots()
    ax.plot([0, 1, 2], [1.0, 2.0, 1.5])
    fig.savefig(path)
    plt.close(fig)


try:
    # --- png only, which is every plot that does not ask ------------------
    rec = plot_store.create_plot(None, "custom", "Plain", {}, ["jobaaaa"])
    pid = rec["plot_id"]
    rec = plot_store.add_version(None, pid, draw)
    v = plot_store.latest_version(rec)
    check("a plot that asked for nothing gets a PNG",
          plot_store.version_path(None, pid, v) is not None)
    check("and records no vector companion",
          plot_store.version_format(rec, v) == "png" and not rec.get("version_formats"),
          "a record that never asked carries no extra key at all")

    # --- svg ---------------------------------------------------------------
    rec = plot_store.add_version(None, pid, draw, fmt="svg")
    v2 = plot_store.latest_version(rec)
    png = plot_store.version_path(None, pid, v2)
    svg = plot_store.version_path(None, pid, v2, ext="svg")
    check("asking for SVG still writes the displayable PNG", png is not None,
          "three views render a version in an <img>; losing the PNG blanks all of them")
    check("asking for SVG writes an SVG beside it", svg is not None)
    check("the SVG really is one",
          svg is not None and svg.read_text(errors="ignore").lstrip()[:200].find("<svg") != -1,
          "matplotlib picks the format off the extension; this is what proves it took")
    check("the version records its format", plot_store.version_format(rec, v2) == "svg")
    check("version_path still defaults to PNG",
          plot_store.version_path(None, pid, v2) == png,
          "the runners record a plot path as a job artifact and the drawer displays it")

    # --- pdf ---------------------------------------------------------------
    rec = plot_store.add_version(None, pid, draw, fmt="pdf")
    v3 = plot_store.latest_version(rec)
    pdf = plot_store.version_path(None, pid, v3, ext="pdf")
    check("asking for PDF writes a PDF beside the PNG",
          pdf is not None and pdf.read_bytes()[:5] == b"%PDF-")
    check("a PDF version is still displayable as PNG",
          plot_store.version_path(None, pid, v3) is not None,
          "this is the case that rules out replacing the PNG rather than adding to it")

    # --- pruning takes both files -----------------------------------------
    for _ in range(plot_store.MAX_VERSIONS + 2):
        rec = plot_store.add_version(None, pid, draw, fmt="svg")
    kept = set(rec["versions"])
    check("pruning keeps only MAX_VERSIONS", len(kept) == plot_store.MAX_VERSIONS)
    leftovers = sorted(p.name for p in (tmp / pid).glob("v*.*")
                       if p.name.rsplit(".", 1)[0] not in kept)
    check("pruning deletes a stale version's vector too, not only its PNG",
          not leftovers,
          "a leaked file per edit would count against the owner's quota with nothing pointing at it: %s"
          % ", ".join(leftovers) if leftovers else "no orphaned files")
    check("and forgets its recorded format",
          set(rec.get("version_formats") or {}) <= kept)
finally:
    plot_store.PLOTS_DIR = real_dir
    shutil.rmtree(tmp, ignore_errors=True)

print("\n%d failure(s)" % len(failures))
sys.exit(1 if failures else 0)

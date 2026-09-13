#!/usr/bin/env python3
"""P5.5 / R-079: two charts drawn at the same time come out right.

    PYTHONPATH=$PWD python3 tests/backend/plot_04_concurrent_render.py

Every renderer in app/chemistry/spectrum.py and app/chemistry/job_charts.py
draws through the pyplot state machine. `plt.rc_context(...)` mutates a global
rcParams dict for the duration of a block and `plt.subplots()` registers the
figure in a global manager, and matplotlib documents pyplot as not
thread-safe. These renderers are called from FastAPI's request threadpool and
from the orchestrator threads, so two of them genuinely can overlap: one
handler alone (`server/routes/jobs.py`'s spectrum route) has three call sites.

What goes wrong is not a wrong number, it is a wrong chart: a figure drawn
under another render's rcParams gets the other one's fonts, sizes or colours.
This project treats a chart as a scientific artifact rather than decoration,
which is why that counts as a defect at all.

HOW THIS IS CHECKED, and why it is a byte comparison.

The same spectrum is rendered four times on its own, serially, with a
deliberately distinctive style (a large font and a specific figure size). The
serial PNG is the reference: it is what that call is supposed to produce.
Then EIGHT renders run at once on eight threads, four in that distinctive
style and four in the default one, interleaved as hard as the machine will
interleave them. Every distinctive render must come out byte-identical to the
serial reference, and every default render byte-identical to a serial default
reference.

Byte equality is the right criterion here because the input is fixed and
matplotlib's Agg backend is deterministic for a fixed input and a fixed style:
two renders of the same data in the same style differ only if something
outside the call changed the style underneath it, which is exactly the defect.
The serial pass at the top proves the determinism rather than assuming it: if
four serial renders of the same thing did not match each other, the criterion
would be wrong and this script says so instead of blaming the threads.

CONCURRENCY is 8 threads and 3 rounds, and the numbers are not arbitrary: 8 is
the number of pyplot call sites across the two modules, and three rounds gives
the interleaving more than one chance to land badly. A single round passing
proves less than it looks, because a race can simply not happen.
"""
from __future__ import annotations

import hashlib
import sys
import tempfile
import threading
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tests"))

from fixtures import check, summary  # noqa: E402

THREADS = 8
ROUNDS = 3
SERIAL_REPEATS = 4

ENERGIES = [3.10, 4.25, 4.88, 5.60, 6.02]
STRENGTHS = [0.012, 0.180, 0.041, 0.330, 0.075]


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def main() -> None:
    try:
        from app.chemistry.plot_style import PlotStyle
        from app.chemistry.spectrum import render_uvvis_plot
    except Exception as exc:  # noqa: BLE001
        check("the spectrum renderers import", False, f"{type(exc).__name__}: {exc}")
        summary()
        return

    # Two styles that differ in things rcParams carries, so a figure drawn
    # under the wrong one is visibly, byte-wise different.
    try:
        loud = PlotStyle(figsize=(9.0, 3.0), dpi=110, font_size=17)
        plain = PlotStyle()
    except TypeError:
        # PlotStyle's field names differ; fall back to whatever it accepts, so
        # this script reports a real result rather than a constructor error.
        loud = PlotStyle(figsize=(9.0, 3.0), dpi=110)
        plain = PlotStyle()

    tmp = Path(tempfile.mkdtemp(prefix="plot04-"))

    def render(style, out: Path) -> None:
        render_uvvis_plot(ENERGIES, STRENGTHS, 0.30, str(out), style=style)

    print("\n== the same call, run serially, is byte-for-byte reproducible ==")
    serial_loud = []
    serial_plain = []
    for i in range(SERIAL_REPEATS):
        a, b = tmp / f"serial_loud_{i}.png", tmp / f"serial_plain_{i}.png"
        render(loud, a)
        render(plain, b)
        serial_loud.append(_digest(a))
        serial_plain.append(_digest(b))
    print(f"  loud style, {SERIAL_REPEATS} serial renders: {sorted(set(serial_loud))}")
    print(f"  plain style, {SERIAL_REPEATS} serial renders: {sorted(set(serial_plain))}")
    reproducible = len(set(serial_loud)) == 1 and len(set(serial_plain)) == 1
    check(
        f"{SERIAL_REPEATS} serial renders of each style agree, so byte equality is a fair test",
        reproducible,
        f"loud={sorted(set(serial_loud))} plain={sorted(set(serial_plain))}",
    )
    if not reproducible:
        print("  the criterion itself does not hold on this matplotlib build; "
              "the concurrency result below would not mean anything, so it is skipped.")
        summary()
        return

    want_loud, want_plain = serial_loud[0], serial_plain[0]

    print(f"\n== {THREADS} renders at once, {ROUNDS} rounds, must match those references ==")
    mismatches: list[str] = []
    for round_i in range(ROUNDS):
        results: dict[int, tuple[str, str]] = {}
        lock = threading.Lock()
        start = threading.Barrier(THREADS)

        def worker(i: int) -> None:
            style, want = (loud, want_loud) if i % 2 == 0 else (plain, want_plain)
            out = tmp / f"c{round_i}_{i}.png"
            start.wait()  # every thread enters the renderer at the same moment
            render(style, out)
            with lock:
                results[i] = (_digest(out), want)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(THREADS)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        bad = [f"round {round_i} thread {i}: got {got}, wanted {want}"
               for i, (got, want) in sorted(results.items()) if got != want]
        mismatches.extend(bad)
        print(f"  round {round_i + 1}: {THREADS - len(bad)}/{THREADS} matched their serial reference")

    check(
        f"all {THREADS * ROUNDS} concurrent renders match the style they asked for",
        not mismatches,
        "; ".join(mismatches[:4]) + (f" (+{len(mismatches) - 4} more)" if len(mismatches) > 4 else ""),
    )

    print("\n== and the lock is where the reason for it is written down ==")
    import inspect
    from app.chemistry import job_charts, spectrum
    for name, mod in (("spectrum.py", spectrum), ("job_charts.py", job_charts)):
        src = inspect.getsource(mod)
        n_ctx = src.count("plt.rc_context(st.rc())")
        n_locked = src.count("figure_lock(), plt.rc_context(st.rc())")
        check(f"every pyplot render in {name} is inside the lock ({n_ctx} of them)",
              n_ctx > 0 and n_ctx == n_locked, f"{n_locked} of {n_ctx} locked")

    summary()


if __name__ == "__main__":
    main()

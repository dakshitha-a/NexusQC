# P5.5, R-079: matplotlib's global state under concurrent renders

`tests/backend/plot_04_concurrent_render.py`, before and after the fix, in
this directory.

## What was measured

The same UV/Vis spectrum (five transitions, fixed energies and oscillator
strengths, 0.30 eV broadening) rendered by `render_uvvis_plot` in two
deliberately different styles: a "loud" one at 9.0 x 3.0 inches, 110 dpi and
17 pt base font, and the project default at 8.0 x 6.0 inches, 300 dpi and 13 pt.

First, four serial renders of each style, to establish that matplotlib's Agg
backend is deterministic here and therefore that byte equality is a fair
criterion. It is: all four renders of each style hashed identically, both
before and after the fix.

Then eight renders at once on eight threads, all released from a barrier so
they enter the renderer together, four in each style, repeated for three
rounds. Twenty-four renders in total. Each is compared byte for byte against
the serial reference for the style it asked for. A mismatch means that render
picked up the other style's rcParams, which is what the finding predicted from
a code read.

Eight threads is the number of pyplot call sites in `app/chemistry/spectrum.py`;
three rounds because a race that does not happen once proves nothing.

## Result

| | serial renders agreeing | concurrent renders matching their own style |
|---|---|---|
| before (`f6d12c5`) | 4/4 loud, 4/4 plain | **6 of 24** (1/8, 3/8, 2/8 by round) |
| after | 4/4 loud, 4/4 plain | **24 of 24** (8/8, 8/8, 8/8) |

So three quarters of concurrent renders came out in the wrong style. The
finding was filed as "suspected (code read), not yet reproduced"; it
reproduces, and it is not marginal.

The failure is cosmetic in the sense that no number in the chart is wrong, and
not cosmetic in the sense that matters here: a spectrum exported at the wrong
figure size and font is not the figure the person asked for, and nothing in the
app tells them it happened.

## The fix

`app/chemistry/plot_style.py` gains one process-wide `figure_lock()`, and all
thirteen `plt.rc_context(st.rc())` blocks across `spectrum.py` (8) and
`job_charts.py` (5) are held under it. One lock rather than one per module,
because the state being protected is a single global. It is held only for the
draw, on the order of a tenth of a second, so concurrent plot requests queue
briefly instead of colliding.

The object-oriented `Figure()` plus `FigureCanvasAgg` API with an explicit
rcParams dict needs no global state at all and is the better end state. It is
also a rewrite of thirteen renderers, and this is the change that makes the
current ones correct.

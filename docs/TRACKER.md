# Active Tracker: none

No plan is currently in motion. The last one closed on 2026-08-28.

This file is always whichever tracker is active, and there is exactly one at
a time. When a plan finishes it is moved to [`trackers/`](trackers/) and a
fresh file starts here for whatever comes next; between the two, this stands
in so `scripts/check_tracker.py` and the links to this path still resolve.

[`docs/BACKLOG.md`](BACKLOG.md) is where the next plan comes from. What is
open there right now:

- Prose guards on invented parameters hold, but not reliably. Thirteen
  required parameters carry a "ONLY set this when the user has said..."
  instruction, which measured 2 of 3 on a repeat probe. The parameters where
  a wrong value is silently plausible want a structural guard rather than a
  probabilistic one.

The two most recent closures:

- [`trackers/2026-08-cap-across-ticks.md`](trackers/2026-08-cap-across-ticks.md)
  the concurrency cap now holds between dispatcher passes and not only within
  one, which also restored the round-robin fairness it had made look broken.
  6 steps across three phases, closed 2026-08-28.
- [`trackers/2026-08-update-knows-what-it-runs.md`](trackers/2026-08-update-knows-what-it-runs.md)
  `scripts/update.sh` now asks the deployment what it is running rather than
  the checkout, and its recovery advice matches what the update actually did.
  10 steps across four phases, closed 2026-08-28.

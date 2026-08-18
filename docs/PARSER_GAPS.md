# Parser gaps

Data a job preview needs but which we cannot yet parse out of an engine's
real output. This file exists so those gaps are **tracked and visible**
rather than silently dropped: a feature ships with the datum marked
"pending output excerpt" in the UI, and the row below records what is
needed to close it.

## Protocol

1. Before writing any ORCA/BAGEL parser, run a **cheap real calculation**
   for that method and job type (water/STO-3G class) and write the parser
   against the actual output — exact formatting is not guaranteed across
   versions, so documentation is not a substitute. PySCF is derived from
   docstrings and returned objects instead.
2. If a datum still cannot be located in that output, add a row here rather
   than guessing at a regex or blocking the phase.
3. The user reviews open rows and supplies output excerpts showing the datum
   in a real run; the parser is then written against the excerpt and the row
   is closed with the commit that did it.

Status values: `open` (needs excerpt) · `excerpt-received` · `closed`.

## Open rows

| Engine | Task / subtype | Method | Datum | What is needed | Status |
|--------|----------------|--------|-------|----------------|--------|
| _(none yet — populated from Phase 0 spikes onward)_ | | | | | |

## Closed rows

| Engine | Task / subtype | Datum | Closed by | Date |
|--------|----------------|-------|-----------|------|
| _(none yet)_ | | | | |

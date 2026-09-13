# P3.1, the knowledge base

`kb_01-before.log` is 1 of 17; `kb_01-after.log` is 16 of 17.

The one remaining failure is the live half and it is expected here: the
deployment still runs the code from the Phase 1 gate, so an admin previewing
another user's source still gets a 404. It turns green at the Phase 3 gate,
once `update.sh` has rebuilt the stack, and the gate's own log records it.
See the tracker's rule 2 for why route tests are timed that way.

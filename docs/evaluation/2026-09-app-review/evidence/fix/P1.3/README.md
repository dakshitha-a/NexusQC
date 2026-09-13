
## A correction made at the Phase 1 gate

`R-002-before.log` records the live probes as `[FAIL] ... is refused -- HTTP
201`, because the test as first written expected the routes to reject a name
carrying a directory. The fix sanitises instead: it takes the last path
component and re-checks containment, which is exactly what the READ path in
the same module has always done, and the response reports the sanitised name
back rather than the one that was sent.

So the assertion was rewritten at the gate to check the property that actually
matters, which is that the write lands inside the caller's own upload
directory, and the file the probe leaves there is cleaned up. What the
before-log records is unchanged and is the finding itself: the writes were
accepted and the files landed at `data/r002-probe-marker.txt` and
`data/uploads/r002-probe-marker.txt`, outside any per-user directory, sent by
an account minutes old. The gate's re-run is
`../P1.8/sec_12_kb_path_safety-after.log`, 27/27 with 2 skipped.

# Gate 2, and why its first backend run was thrown away

## The void run

`backend-run-VOID-wrong-port.log` is kept, not deleted, because a 47-failure
log that looks exactly like a broad regression and is not one is worth having
on the record.

It reported `SUMMARY: 111/158 scripts reported all checks passing`, with every
`sec_*`, every `p1_*`, every `share_*` and every `proj_*` script among the
failures. All of them failed the same way, at their first HTTP call, with
`httpcore.ConnectError: [Errno 111] Connection refused`, starting with
`_00_bootstrap.py`, the very first script in the run.

The cause is the one `CLAUDE.local.md` warns about in as many words. This
host's `docker-compose.override.yml` remaps nginx to 8444, while the tracked
`docker-compose.yml` and `tests/fixtures.py` both assume 8443, so the suite has
to be told where the stack is:

```bash
QC_AGENT_TEST_BASE_URL=https://127.0.0.1:8444 bash tests/run_backend.sh
```

This run was launched without it. Confirmed after the fact rather than
inferred: `curl https://127.0.0.1:8443/api/health` returns nothing (connection
refused) and `https://127.0.0.1:8444/api/health` returns 200. The note in
`CLAUDE.local.md` says the symptom "reads exactly like a broad regression
rather than a wrong port", which is precisely how it read.

Two things in that log are still real, because they are in-process and never
touch the network, and both were fixed rather than dismissed:

- `chain_01_ready_draft_submits.py`, 4 failures. Its last section asserted the
  pre-R-101 default, that a ready draft stops at "DRAFT READY" and opens no
  approval card. R-101 flipped that default and `preview_only=True` is the
  opt-out now. The section was rewritten and a new one checks the new default.
- `fail_01_notice_flow.py`, 1 failure. The assertion was stale, but chasing it
  found a real bug in this run's own R-014 fix: the troubleshoot prompt was
  rewritten to say `search(kind='manuals')` and the tool's argument is
  `source`. Naming a real tool with an argument it does not take fails exactly
  the way naming a tool that does not exist does, which is what R-014 was
  about. Fixed in `app/agent/troubleshoot.py`.

`conf_04_pool_redis_cold_start_race.py`'s failure is also worth keeping in
mind for the real run: it restarts the api container and waits 60 s for health,
while `docker-compose.yml`'s own comment puts the api health check at about
ninety seconds. That may be a harness timeout rather than anything about the
code, and it is measured in the real run rather than assumed here.

## What replaced it

Gate 2 and Gate 3 were merged into one gate rather than run twice. By the time
the void run was diagnosed, Phase 5 was committed as well, so a second run
against a Phase-3 stack would have tested a deployment that no longer matched
the working tree, while the in-process scripts imported Phase 5 code from it.
One gate against a stack and a tree that agree is a better measurement than two
half-valid ones.

The before-logs that genuinely needed the pre-Phase-5 deployment were taken
first, while the stack was still on `f6d12c5`; they are in the `P5.2` and `P5.3`
directories. The combined gate's logs are in `P6.2`.

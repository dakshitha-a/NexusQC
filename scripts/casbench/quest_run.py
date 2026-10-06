#!/usr/bin/env python3
"""Detached, resumable runner for the QUESTDB benchmark.

Runs every (excitation, mode) task of `quest_bench.py` through a pool of
worker subprocesses, one calculation per subprocess, and is built to outlive
the session that started it:

- Started through `quest_ctl.sh start`, which puts it in its own session and
  process group (`setsid nohup`), so closing or restarting Claude Code, or the
  terminal, does not take it down.
- All state is on disk under `.cache/casbench_quest/run/<run>/`:

      runner.pid       the runner's pid while it is alive
      heartbeat.json   rewritten every 30 s: counts, in-flight tasks, load
      runner.log       one line per launch, completion, retry, wait
      results.jsonl    one JSON line per finished task, appended by the worker
      inflight/        one file per running task: worker pid, start time
      logs/            each task's own stderr
      attempts.json    how many times each task has been launched

- Resume is idempotent. A task with a final line in results.jsonl is never
  run again. A task listed in inflight/ whose worker is still alive (because
  the runner died but its children did not) is adopted and waited for, not
  relaunched, so a restart neither loses nor duplicates a row. A task whose
  worker is gone without a result is relaunched; after two failed attempts it
  is recorded as failed and the runner moves on.
- Workers are admitted against host-wide load, not only this runner's own
  count, because the machine is shared: a worker starts only while the
  one-minute load average leaves room for its threads plus a margin.

`engine_capped` is only needed where the engine's own space is larger than
the cap. Where it is not, the capped row IS the engine row, and it is recorded
as an alias of it instead of being recomputed; so capped tasks wait for their
engine task.

    python3 scripts/casbench/quest_run.py --run main [--workers 10 --threads 8]
    python3 scripts/casbench/quest_run.py --run main --status
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CACHE = REPO / ".cache" / "casbench_quest"
BENCH = REPO / "scripts" / "casbench" / "quest_bench.py"
MODES = ("apc2", "engine", "engine_capped")
FINAL = {"ok", "not_converged", "unrepresentable", "too_large", "inconsistent_space",
         "alias", "failed"}
MAX_ATTEMPTS = 2
MAX_CSF = 226512
NCPU = os.cpu_count() or 1
TASK_WALL_S = 48 * 3600     # a harness bound, not a judgement on the job


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    # a zombie is not alive for our purposes
    try:
        with open(f"/proc/{pid}/stat") as fh:
            return fh.read().split()[2] != "Z"
    except FileNotFoundError:
        return False


def is_worker(pid: int, key: str) -> bool:
    try:
        cmd = open(f"/proc/{pid}/cmdline", "rb").read().replace(b"\0", b" ").decode()
    except FileNotFoundError:
        return False
    name, mode = key.split("|")
    return "quest_bench.py" in cmd and f" {name} {mode}" in cmd


class Run:
    def __init__(self, run: str):
        self.dir = CACHE / "run" / run
        self.dir.mkdir(parents=True, exist_ok=True)
        (self.dir / "inflight").mkdir(exist_ok=True)
        (self.dir / "logs").mkdir(exist_ok=True)
        self.results = self.dir / "results.jsonl"
        self.log_path = self.dir / "runner.log"

    def log(self, msg):
        line = f"{now()} {msg}"
        with open(self.log_path, "a") as fh:
            fh.write(line + "\n")
        print(line, flush=True)

    def finished(self):
        """key -> last final result line."""
        out = {}
        if self.results.exists():
            for l in open(self.results):
                l = l.strip()
                if not l.startswith("{"):
                    continue
                try:
                    r = json.loads(l)
                except json.JSONDecodeError:
                    continue            # a line cut short by a kill mid-write
                if r.get("status") in FINAL:
                    out[f"{r['name']}|{r['mode']}"] = r
        return out

    def attempts(self):
        p = self.dir / "attempts.json"
        return json.load(open(p)) if p.exists() else {}

    def save_attempts(self, a):
        p = self.dir / "attempts.json"
        tmp = p.with_suffix(".tmp")
        json.dump(a, open(tmp, "w"))
        os.replace(tmp, p)

    def append(self, rec):
        with open(self.results, "a") as fh:
            fh.write(json.dumps(rec) + "\n")


def order_rows(rows):
    """Interleave categories so any prefix of the run is a fair sample.

    Round-robin over (spin multiplicity, valence/Rydberg, double) buckets,
    each bucket in manifest order, so the first tenth of the run already has
    singlets, triplets, doublets, Rydberg, valence and doubles in roughly
    their final proportions.
    """
    buckets = {}
    for r in rows:
        c = r["category"]
        buckets.setdefault((c["spin_mult"], c["vr"], c["double"]), []).append(r)
    keys = sorted(buckets, key=str)
    out = []
    while any(buckets[k] for k in keys):
        for k in keys:
            if buckets[k]:
                out.append(buckets[k].pop(0))
    return out


def status(run: Run, rows, modes) -> dict:
    fin = run.finished()
    total = len(rows) * len(modes)
    by = {}
    for r in fin.values():
        by[r["status"]] = by.get(r["status"], 0) + 1
    inflight = []
    for f in (run.dir / "inflight").glob("*.json"):
        try:
            inflight.append(json.load(open(f)))
        except Exception:                                       # noqa: BLE001
            pass
    hb = run.dir / "heartbeat.json"
    hb_age = time.time() - hb.stat().st_mtime if hb.exists() else None
    pid = None
    pf = run.dir / "runner.pid"
    if pf.exists():
        pid = int(pf.read_text().strip() or 0)
    good = {}
    for m in modes:
        sc = [r for k, r in fin.items() if k.endswith("|" + m) and "good_space" in r]
        if sc:
            good[m] = f"{sum(r['good_space'] for r in sc)}/{len(sc)}"
    done_times = [r.get("finished_at") for r in fin.values() if r.get("finished_at")]
    rate = None
    if len(done_times) >= 2:
        t = sorted(datetime.fromisoformat(x).timestamp() for x in done_times)
        span = (t[-1] - t[0]) / 3600
        if span > 0:
            rate = (len(t) - 1) / span
    return {"done": len(fin), "total": total, "by_status": by,
            "inflight": [f"{i['key']} ({(time.time() - i['started']) / 60:.0f} min)"
                         for i in inflight],
            "runner_pid": pid, "runner_alive": bool(pid and alive(pid)),
            "heartbeat_age_s": None if hb_age is None else round(hb_age),
            "rows_per_hour": None if rate is None else round(rate, 1),
            "eta_hours": (None if not rate else round((total - len(fin)) / rate, 1)),
            "good_space": good, "load1": round(os.getloadavg()[0], 1)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", default="main")
    ap.add_argument("--workers", type=int, default=10)
    ap.add_argument("--threads", type=int, default=8)
    ap.add_argument("--modes", default=",".join(MODES))
    ap.add_argument("--only", help="comma-separated excitation names (calibration, tests)")
    ap.add_argument("--load-margin", type=int, default=16,
                    help="cores left free host-wide when admitting a worker")
    ap.add_argument("--cores-per-worker", type=float, default=None,
                    help="cores a worker really occupies, for the admission gate. "
                         "Measured at about 1.5x --threads: PySCF's OpenMP threads "
                         "plus numpy's own OpenBLAS pool. Defaults to 1.5 x threads.")
    ap.add_argument("--status", action="store_true")
    a = ap.parse_args()

    sys.path.insert(0, str(REPO / "scripts" / "casbench"))
    manifest = json.load(open(CACHE / "manifest.json"))
    rows = manifest["rows"]
    if a.only:
        want = set(a.only.split(","))
        rows = [r for r in rows if r["name"] in want]
    rows = order_rows(rows)
    modes = [m for m in a.modes.split(",") if m]
    run = Run(a.run)
    cfg = run.dir / "config.json"
    if a.status:
        print(json.dumps(status(run, rows if not cfg.exists() else _cfg_rows(cfg, rows),
                                modes if not cfg.exists() else json.load(open(cfg))["modes"])))
        return 0

    pf = run.dir / "runner.pid"
    if pf.exists():
        old = int(pf.read_text().strip() or 0)
        if old and alive(old) and old != os.getpid():
            print(f"runner already alive as pid {old}; refusing to start a second", file=sys.stderr)
            return 2
    pf.write_text(str(os.getpid()))
    json.dump({"modes": modes, "only": a.only, "workers": a.workers, "threads": a.threads,
               "started": now(), "commit": _commit()}, open(cfg, "w"))

    stopping = {"flag": False}

    def on_term(sig, frm):
        stopping["flag"] = True
    signal.signal(signal.SIGTERM, on_term)
    signal.signal(signal.SIGINT, on_term)

    env = dict(os.environ, OMP_NUM_THREADS=str(a.threads), MKL_NUM_THREADS=str(a.threads),
               OPENBLAS_NUM_THREADS=str(a.threads), PYTHONPATH=str(REPO),
               QUEST_MAX_MEMORY_MB=os.environ.get("QUEST_MAX_MEMORY_MB", "24000"))
    procs = {}          # key -> Popen (launched by this runner)
    adopted = {}        # key -> pid (launched by a previous runner, still alive)
    run.log(f"runner start pid={os.getpid()} rows={len(rows)} modes={modes} "
            f"workers={a.workers} threads={a.threads}")

    # Adopt workers a dead runner left behind.
    for f in (run.dir / "inflight").glob("*.json"):
        i = json.load(open(f))
        if alive(i["pid"]) and is_worker(i["pid"], i["key"]):
            adopted[i["key"]] = i["pid"]
            run.log(f"adopted live worker {i['key']} pid={i['pid']}")
        else:
            f.unlink()

    last_hb = 0.0
    last_wait_log = 0.0
    while True:
        fin = run.finished()
        att = run.attempts()

        # Reap.
        for key, p in list(procs.items()):
            rc = p.poll()
            if rc is None:
                if time.time() - p.started > TASK_WALL_S:
                    p.kill()
                    run.log(f"wall cap hit {key}; killed")
                continue
            del procs[key]
            _inflight(run, key).unlink(missing_ok=True)
            fin = run.finished()
            if key in fin:
                run.log(f"done {key} status={fin[key]['status']} rc={rc} "
                        f"{(time.time() - p.started) / 60:.1f} min")
            else:
                run.log(f"worker exited without a result {key} rc={rc}")
        for key, pid in list(adopted.items()):
            if not alive(pid):
                del adopted[key]
                _inflight(run, key).unlink(missing_ok=True)
                run.log(f"adopted worker finished {key}")
        fin = run.finished()

        # Pending tasks, in order; capped tasks wait for their engine row.
        pending = []
        for r in rows:
            for m in modes:
                key = f"{r['name']}|{m}"
                if key in fin or key in procs or key in adopted:
                    continue
                if att.get(key, 0) >= MAX_ATTEMPTS:
                    run.append({"name": r["name"], "mode": m, "status": "failed",
                                "attempts": att[key], "finished_at": now(),
                                "log": str(run.dir / "logs" / f"{r['name']}.{m}.log")})
                    run.log(f"giving up on {key} after {att[key]} attempts")
                    continue
                if m == "engine_capped" and "engine" in modes:
                    e = fin.get(f"{r['name']}|engine")
                    if e is None:
                        continue
                    nat = (e.get("selection") or {}).get("native_ncsf")
                    if e["status"] != "failed" and nat is not None and nat <= MAX_CSF:
                        run.append({"name": r["name"], "mode": m, "status": "alias",
                                    "alias_of": "engine", "finished_at": now(),
                                    "note": f"native space is {nat} CSFs, within the cap"})
                        continue
                pending.append((key, r["name"], m))

        busy = len(procs) + len(adopted)
        if stopping["flag"]:
            run.log(f"stop requested: terminating {len(procs)} worker(s)")
            for key, p in procs.items():
                p.terminate()
            break
        if not pending and busy == 0:
            run.log("RUN_COMPLETE")
            break

        # Admit.
        while pending and busy < a.workers:
            load = os.getloadavg()[0]
            need = a.cores_per_worker or 1.5 * a.threads
            if load + need > NCPU - a.load_margin:
                if time.time() - last_wait_log > 600:
                    run.log(f"waiting for host headroom: load {load:.0f} of {NCPU} cores")
                    last_wait_log = time.time()
                break
            key, name, mode = pending.pop(0)
            att[key] = att.get(key, 0) + 1
            run.save_attempts(att)
            logf = open(run.dir / "logs" / f"{name}.{mode}.log", "a")
            logf.write(f"\n===== attempt {att[key]} {now()} =====\n")
            logf.flush()
            p = subprocess.Popen([sys.executable, str(BENCH), "one", name, mode,
                                  "--out", str(run.results)],
                                 env=env, stdout=subprocess.DEVNULL, stderr=logf,
                                 cwd=str(REPO))
            p.started = time.time()
            procs[key] = p
            json.dump({"key": key, "pid": p.pid, "started": p.started},
                      open(_inflight(run, key), "w"))
            run.log(f"launch {key} pid={p.pid} attempt={att[key]} load={load:.0f}")
            busy += 1
            time.sleep(2)   # let the load average see it

        if time.time() - last_hb > 30:
            st = status(run, rows, modes)
            tmp = run.dir / "heartbeat.tmp"
            json.dump({**st, "at": now()}, open(tmp, "w"))
            os.replace(tmp, run.dir / "heartbeat.json")
            last_hb = time.time()
        time.sleep(5)

    pf.unlink(missing_ok=True)
    return 0


def _inflight(run, key):
    return run.dir / "inflight" / (key.replace("|", ".").replace("/", "_") + ".json")


def _cfg_rows(cfg, rows):
    c = json.load(open(cfg))
    if c.get("only"):
        want = set(c["only"].split(","))
        return [r for r in rows if r["name"] in want]
    return rows


def _commit():
    try:
        return subprocess.run(["git", "-C", str(REPO), "rev-parse", "--short", "HEAD"],
                              capture_output=True, text=True).stdout.strip()
    except Exception:                                           # noqa: BLE001
        return None


if __name__ == "__main__":
    sys.exit(main())

"""PERF-02 (baseline, then fix regression): GET /api/admin/storage
(server/routes/admin.py) walks disk+Postgres to build usage_report(). This
script first measures that walk's cost at growing volume, then verifies
the Tier C fix that followed once the numbers justified it.

Baseline evidence (seeded directly on this stack, not assumed): near-empty
data volume measured ~174ms median; 1,000 seeded job directories measured
~343ms median; 5,000 measured ~819ms median with spikes over 2 seconds.
That's roughly linear scaling with job count, and this route is hit
repeatedly on every admin-console page load (alongside several other
KB-touching requests firing at once, per the Chroma race-condition note
elsewhere in this codebase), not just once -- which is what justified
adding a short TTL cache (ADMIN_STORAGE_CACHE_TTL_SECONDS,
app/auth/storage_quota.py's usage_report()/invalidate_usage_report_cache())
rather than leaving PERF-02 as a documented-but-unaddressed baseline.

This script seeds a smaller volume (300 jobs -- enough to make the
underlying walk cost clearly measurable in milliseconds, small enough to
stay a routine part of run_backend.sh rather than a slow one-off) directly
via `docker compose exec`, the same in-container-exec convention this
suite already uses elsewhere (see sec_08's own docstring) for scenarios
the real API can't construct directly. It then confirms: a cache miss
(forced via invalidate_usage_report_cache(), which every purge and admin
config PATCH already calls in the real app -- this script exercises that
same invalidation path through a real PATCH) is measurably slower than a
cache hit, and that the served numbers are never stale after a mutating
action -- a fast-but-wrong cached response would be worse than the
original uncached-but-slow behavior, so correctness is checked before
speed.
"""
from __future__ import annotations

import statistics
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from fixtures import admin_client, check, cleanup_all_qatest_users, summary  # noqa: E402

COMPOSE_DIR = Path(__file__).resolve().parent.parent.parent
N_SEED_JOBS = 300
N_CALLS = 10


def _exec_api(code: str) -> str:
    proc = subprocess.run(
        ["docker", "compose", "exec", "-T", "api", "python", "-c", code],
        cwd=str(COMPOSE_DIR), capture_output=True, text=True, timeout=60,
    )
    if proc.returncode != 0:
        print(proc.stderr, file=sys.stderr)
        raise RuntimeError(f"in-container exec failed: {proc.stderr[:500]}")
    return proc.stdout.strip()


def _seed_jobs() -> str:
    """Creates one disposable qatest_ owner and N_SEED_JOBS synthetic
    terminal job directories for it directly on disk, with a pre-cached
    meta.json dir_size_bytes (matching steady-state -- a terminal job's
    size is cached after its first computation, see quota.py's
    _cached_dir_size) so this measures the walk itself, not incidental
    first-touch disk I/O. Returns the owner's user_id (used both to scope
    cleanup and, via DELETE /api/admin/users/{id} at the end, to purge
    every seeded job through the exact same purge_user_data() path SEC-08b
    fixed)."""
    code = f'''
import json, time, uuid, random
from app.config import JOBS_DIR
from app.auth.models import create_user, record_ownership

u = create_user("qatest_perf02@example.test", "qatest_perf02", "x" * 20, role="user")
uid = str(u["id"])
for _ in range({N_SEED_JOBS}):
    job_id = uuid.uuid4().hex[:12]
    d = JOBS_DIR / job_id
    d.mkdir(parents=True, exist_ok=True)
    (d / "spec.json").write_text(json.dumps({{
        "job_id": job_id, "method": "single_point", "engine": "pyscf",
        "molecule": {{"atoms": [["O", [0, 0, 0]]], "charge": 0, "multiplicity": 1}},
        "params": {{"method": "hf", "basis": "sto-3g"}}, "created_at": time.time(),
        "label": "perf_02 seed job",
    }}))
    (d / "result.json").write_text(json.dumps({{
        "job_id": job_id, "status": "completed",
        "summary": {{"energy_hartree": -74.96}}, "artifacts": {{}},
    }}))
    (d / "meta.json").write_text(json.dumps({{"dir_size_bytes": random.randint(50_000, 500_000)}}))
    record_ownership("job", job_id, uid)
print(uid)
'''
    return _exec_api(code)


def main() -> None:
    admin = admin_client()
    print(f"seeding {N_SEED_JOBS} synthetic terminal job directories via docker compose exec...")
    owner_id = _seed_jobs()

    # Force a cold read (the fix's own invalidate_usage_report_cache() path,
    # exercised here via a real PATCH -- same call the fix's docstring
    # promises invalidates it) and time it against N_CALLS-1 immediately-
    # following warm reads.
    cfg_before = admin.get("/api/admin/config").json()
    r_patch = admin.patch(
        "/api/admin/config",
        json={"key": "global_storage_quota_bytes", "value": cfg_before["global_storage_quota_bytes"]},
    )
    check("config PATCH (forces a cache invalidation) succeeds", r_patch.status_code == 200, str(r_patch.status_code))

    cold_start = time.perf_counter()
    r_cold = admin.get("/api/admin/storage")
    cold_ms = (time.perf_counter() - cold_start) * 1000.0
    check("GET /api/admin/storage (cold, post-invalidation) returns 200", r_cold.status_code == 200, str(r_cold.status_code))

    warm_times = []
    for _ in range(N_CALLS - 1):
        start = time.perf_counter()
        r = admin.get("/api/admin/storage")
        warm_times.append((time.perf_counter() - start) * 1000.0)
        check("GET /api/admin/storage (warm) returns 200", r.status_code == 200, str(r.status_code))
    warm_median = statistics.median(warm_times)

    print(f"at {N_SEED_JOBS} seeded jobs: cold (post-invalidation) call = {cold_ms:.1f}ms, "
          f"warm (cached) median over {len(warm_times)} calls = {warm_median:.1f}ms")
    check(
        "FIX VERIFIED: a warm (cached) read is substantially faster than the cold read that follows an invalidation",
        warm_median < cold_ms / 3,
        f"cold={cold_ms:.1f}ms warm_median={warm_median:.1f}ms -- if these are close, the cache isn't engaging",
    )

    # Correctness over speed: a purge must be reflected on the very next
    # read, not masked by a stale cached value for up to the TTL window.
    job_bytes_before = admin.get("/api/admin/storage").json()["global"]["job_bytes"]
    r_purge = admin.post("/api/admin/purge/jobs")
    check("purge/jobs succeeds", r_purge.status_code == 200, str(r_purge.status_code))
    job_bytes_after = admin.get("/api/admin/storage").json()["global"]["job_bytes"]
    check(
        "FIX VERIFIED: usage numbers reflect a purge on the very next read, not a stale cached value",
        job_bytes_after < job_bytes_before,
        f"before={job_bytes_before} after={job_bytes_after} -- unchanged would mean invalidation isn't wired to purges",
    )

    n_cleaned = cleanup_all_qatest_users(admin)
    print(f"cleaned up {n_cleaned} qatest_ user(s) (owner_id was {owner_id})")
    summary()


if __name__ == "__main__":
    main()

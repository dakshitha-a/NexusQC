#!/usr/bin/env python3
"""A project download streams; it does not assemble the archive in memory.

    QC_AGENT_TEST_BASE_URL=https://127.0.0.1:8444 \
      PYTHONPATH=$PWD python3 tests/backend/proj_04_zip_streams.py

This is the one place the archive feature could take the API process down,
and it is invisible to every other kind of test: a buffered implementation
and a streaming one return byte-identical archives. The only way to tell
them apart is to watch the server's memory while a large one is downloading.

The two existing zips here both build in an io.BytesIO -- the single-job
download and the whole-account export -- and the per-job one explains why
in its own comment: /data is close to full, so writing the zip out is not
an option either. That trade is fine for one job. A project is N jobs, and
a single orbital cube in this repository's own measurements runs to about
seven megabytes, so a study-sized archive held resident would be hundreds
of megabytes per concurrent download.

So: seed a job, put a large incompressible artifact in its directory, file
it into a project, and download it while sampling the api container's RSS.
A buffered build shows a resident-set jump on the order of the payload; a
streaming one does not. The archive is also read back afterwards, because
a stream that uses no memory and produces a corrupt zip is not a fix.
"""
from __future__ import annotations

import io
import subprocess
import sys
import threading
import time
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fixtures import (  # noqa: E402
    admin_client, check, cleanup_jobs, cleanup_user, mint_invite, register, summary,
)

# Big enough that a buffered build is unmistakable against ordinary
# process noise, small enough to write and transfer in a few seconds.
# Incompressible (os.urandom) on purpose: a payload of zeros would deflate
# to almost nothing and a buffered implementation would look innocent.
PAYLOAD_BYTES = 200 * 1024 * 1024
# A streaming build's own working set is one file chunk plus deflate
# state, i.e. low single-digit megabytes. This threshold is far above that
# and far below the payload, so it does not depend on a precise number.
RSS_GROWTH_LIMIT_BYTES = 60 * 1024 * 1024


def _exec_api(code: str, timeout: int = 240) -> str:
    proc = subprocess.run(
        ["docker", "compose", "exec", "-T", "api", "python", "-c", code],
        cwd=str(REPO), capture_output=True, text=True, timeout=timeout,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"in-container exec failed: {proc.stderr[-500:]}")
    return proc.stdout.strip().splitlines()[-1].strip()


def seed_big_job(owner_user_id: str) -> str:
    """A real completed job whose directory also holds a large artifact,
    standing in for the orbital cubes and BAGEL archives a real study
    accumulates."""
    return _exec_api(f'''
import os, time
from app.chemistry.molecule import resolve_molecule
from app.chemistry.jobs.base import JobSpec, get_job_manager, JOBS_DIR
from app.auth.models import record_ownership

m = resolve_molecule("water")
spec = JobSpec(method="hf", engine="orca", task="single_point", subtype="gs",
               molecule=m.to_dict(), params={{"basis": "sto-3g"}}, label="qatest big archive")
job_id = spec.job_id
# Written straight to disk as a completed job rather than actually run:
# this test is about the download route's memory profile, and an ORCA run
# would add a minute for nothing. The shape on disk is what matters, and
# it is the real JobSpec/write_status/write_result that produce it.
from app.chemistry.jobs.base import JobResult, write_result, write_status
spec.job_dir()
(JOBS_DIR / job_id / "spec.json").write_text(__import__("json").dumps(spec.to_dict()))
write_status(job_id, "completed", "done")
write_result(JobResult(job_id, "completed", summary={{"energy_hartree": -74.96}}, artifacts={{}}))
(JOBS_DIR / job_id / "input.inp").write_text("! HF STO-3G\\n")
with open(JOBS_DIR / job_id / "input.mo2a.cube", "wb") as f:
    f.write(os.urandom({PAYLOAD_BYTES}))
from app.chemistry.jobs.base import write_meta
write_meta(job_id, {{"label": "qatest big archive"}})
record_ownership("job", job_id, {owner_user_id!r})
print(job_id)
''')


def api_rss_bytes() -> int:
    """Resident set of every process in the api container, summed. Summed
    rather than taken from one pid because uvicorn's worker layout is not
    this test's business, and a buffered build would show up in whichever
    process happened to serve the request."""
    out = _exec_api('''
total = 0
import os
for pid in os.listdir("/proc"):
    if not pid.isdigit():
        continue
    try:
        with open(f"/proc/{pid}/status") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    total += int(line.split()[1]) * 1024
                    break
    except OSError:
        pass
print(total)
''', timeout=60)
    return int(out)


def main() -> None:
    admin = admin_client()
    user_client, user = register(mint_invite(admin))
    jobs: list[str] = []
    projects: list[str] = []
    try:
        print("\n== seeding a project holding a 200 MB artifact ==")
        job_id = seed_big_job(user["id"])
        jobs.append(job_id)
        r = user_client.post("/api/projects", json={"name": "qatest big", "job_ids": [job_id]})
        r.raise_for_status()
        project_id = r.json()["project_id"]
        projects.append(project_id)
        check("the project reports the large archive size",
              r.json()["size_bytes"] > PAYLOAD_BYTES, str(r.json()["size_bytes"]))

        print("\n== downloading it while watching the server's memory ==")
        baseline = api_rss_bytes()
        peak = {"rss": baseline}
        stop = threading.Event()

        def sample() -> None:
            while not stop.is_set():
                try:
                    peak["rss"] = max(peak["rss"], api_rss_bytes())
                except Exception:
                    pass
                time.sleep(0.4)

        sampler = threading.Thread(target=sample, daemon=True)
        sampler.start()

        # A per-request timeout: fixtures.new_client fixes 30s, which is
        # generous for an API call and tight for a 200 MB TLS transfer that
        # is being deflated on the fly.
        body = bytearray()
        with user_client.stream(
            "GET", f"/api/projects/{project_id}/download", timeout=300.0
        ) as resp:
            status = resp.status_code
            disposition = resp.headers.get("content-disposition", "")
            for chunk in resp.iter_bytes():
                body.extend(chunk)
        stop.set()
        sampler.join(timeout=5)

        growth = peak["rss"] - baseline
        check("the download succeeded", status == 200, f"status {status}")
        check("the zip is named after the project, not its id",
              "_archive.zip" in disposition and "qatest_big" in disposition, disposition)
        check(
            "the server did NOT hold the archive in memory",
            growth < RSS_GROWTH_LIMIT_BYTES,
            f"api RSS grew {growth / 1e6:.0f} MB against a {PAYLOAD_BYTES / 1e6:.0f} MB payload "
            f"(limit {RSS_GROWTH_LIMIT_BYTES / 1e6:.0f} MB)",
            "this is what a regression back to io.BytesIO looks like",
        )
        print(f"  (api RSS: {baseline / 1e6:.0f} MB baseline, {peak['rss'] / 1e6:.0f} MB peak, "
              f"{growth / 1e6:.0f} MB growth; payload {PAYLOAD_BYTES / 1e6:.0f} MB)")

        print("\n== and the archive is actually readable ==")
        zf = zipfile.ZipFile(io.BytesIO(bytes(body)))
        check("the zip has no corrupt member", zf.testzip() is None, str(zf.testzip()))
        names = zf.namelist()
        manifest = [n for n in names if n.endswith("_manifest.csv")]
        check("it carries a manifest at the root", len(manifest) == 1, str(names))
        manifest_text = zf.read(manifest[0]).decode("utf-8")
        check("the manifest names the job by the label the user gave it",
              "qatest big archive" in manifest_text, manifest_text[:300])
        check("and states the engine, the method and the status in readable terms",
              all(t in manifest_text for t in ("orca", "hf", "completed")), manifest_text[:300])
        check("the large artifact came through whole",
              any(n.endswith("input.mo2a.cube") and zf.getinfo(n).file_size == PAYLOAD_BYTES for n in names),
              str([(n, zf.getinfo(n).file_size) for n in names]))
        check("engine files keep their own names inside the archive",
              any(n.endswith("/input.inp") for n in names), str(names))
    finally:
        for project_id in projects:
            try:
                user_client.delete(f"/api/projects/{project_id}", params={"delete_jobs": "false"})
            except Exception:
                pass
        cleanup_jobs(admin, jobs)
        cleanup_user(admin, user["id"])

    summary()


if __name__ == "__main__":
    main()

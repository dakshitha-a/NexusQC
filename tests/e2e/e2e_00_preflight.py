"""Bring-up gates for a freshly installed stack. NOTHING ELSE RUNS UNTIL
THIS IS GREEN.

Each gate here corresponds to a deployment bug this repo has actually
shipped at least once (see CLAUDE.md's six-deployment-bugs note). A
--no-cache rebuild re-exposes every one of them, and several fail in ways
that look like an application bug hours later:

  * N_CORES == 255 makes JobManager._wait_for_resources wait for 255 idle
    cores that will never exist, so EVERY job hangs `pending` forever.
    Debugging that from the agent's side wastes an afternoon.
  * No mpirun means every ORCA job with %pal nprocs > 1 dies at startup.
  * A missing libmpi_cxx.so.40 / libboost_serialization means BAGEL cannot
    even start.
  * nginx serves the HOST ./frontend/dist bind mount, which docker compose
    build does not touch -- a stale dist silently serves an old UI.

Run: python3 tests/e2e/e2e_00_preflight.py
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from fixtures import BASE_URL, check, new_client, summary  # noqa: E402

REPO = Path(__file__).resolve().parent.parent.parent


def api(code: str, timeout: int = 120) -> tuple[int, str, str]:
    p = subprocess.run(
        ["docker", "compose", "exec", "-T", "api", "bash", "-lc", code],
        cwd=str(REPO), capture_output=True, text=True, timeout=timeout,
    )
    return p.returncode, p.stdout.strip(), p.stderr.strip()


def main() -> None:
    # ---- G1: health ------------------------------------------------------
    c = new_client()
    t0 = time.perf_counter()
    healthy = False
    for _ in range(120):
        try:
            if c.get("/api/health").status_code == 200:
                healthy = True
                break
        except Exception:
            pass
        time.sleep(1.0)
    boot = time.perf_counter() - t0
    check("G1 /api/health reachable through nginx", healthy, f"{boot:.1f}s after up")
    if not healthy:
        summary()
        return

    # ---- G2: N_CORES -- the one that silently hangs every job ------------
    # NOTE: `nproc` inside the container correctly reports the host's full
    # 255 logical CPUs -- the container has no OMP_NUM_THREADS, unlike this
    # host's own shell profile, which is what makes nproc return 8 there.
    # The ONLY thing keeping N_CORES sane in the deployed stack is the
    # explicit QC_AGENT_N_CORES in docker-compose.yml. That makes it a
    # single point of failure worth asserting on directly, so this gate
    # checks the env var AND the resulting value, not nproc.
    rc, out, _ = api("nproc")
    print(f"    [info] container nproc = {out} (host's full logical CPU count; expected)")
    rc, out, _ = api('echo "${QC_AGENT_N_CORES:-UNSET}"')
    check(
        "G2a QC_AGENT_N_CORES is passed through by docker-compose.yml "
        "(without it N_CORES becomes 255 and every job hangs pending forever)",
        out == "8", f"got {out!r}",
    )
    rc, out, err = api("python3 -c 'from app.config import N_CORES; print(N_CORES)'")
    check("G2b app.config.N_CORES resolves to 8", out == "8", f"got {out!r} {err[:200]}")

    # ---- G3: MPI ---------------------------------------------------------
    rc, out, err = api("mpirun --version 2>&1 | head -1")
    ver = re.search(r"(\d+)\.(\d+)\.(\d+)", out or "")
    check("G3a mpirun present", rc == 0 and bool(out), out or err[:200])
    check(
        "G3b OpenMPI is 4.x (5.x dropped libmpi_cxx.so.40 that BAGEL needs)",
        bool(ver) and ver.group(1) == "4", out,
    )

    # ---- G4: BAGEL shared libraries -------------------------------------
    # Must be checked under the EXACT environment bagel_runner._run_bagel
    # builds, not a bare shell. BAGEL's MKL/Boost/ScaLAPACK/OpenBLAS
    # dependencies are lab-installed under /software and are resolved by
    # sourcing oneAPI's setvars.sh plus prepending BAGEL_EXTRA_LIB_DIRS --
    # both scoped deliberately to BAGEL's own subprocess, never applied
    # container-wide (a universal override risks the wrong library being
    # picked up by PySCF/block2's own MKL needs). A plain `ldd` therefore
    # reports a long list of "not found" that means nothing.
    rc, out, err = api(
        "python3 -c \""
        "import subprocess;"
        "from app.config import BAGEL_BIN, BAGEL_EXTRA_LIB_DIRS, BAGEL_ONEAPI_SETVARS, N_CORES;"
        "cmd = f'source {BAGEL_ONEAPI_SETVARS} > /dev/null 2>&1; "
        "export LD_LIBRARY_PATH=\\\"{BAGEL_EXTRA_LIB_DIRS}:\\$LD_LIBRARY_PATH\\\"; "
        "ldd \\\"{BAGEL_BIN}\\\" 2>&1 | grep -i \\\"not found\\\" || echo CLEAN';"
        "p = subprocess.run(['bash','-c',cmd], capture_output=True, text=True);"
        "print(p.stdout.strip())\""
    )
    check(
        "G4 BAGEL's libraries all resolve under bagel_runner's own scoped "
        "LD_LIBRARY_PATH (oneAPI setvars + BAGEL_EXTRA_LIB_DIRS)",
        "CLEAN" in out, out[:400] or err[:300],
    )

    # ---- G5: ORCA --------------------------------------------------------
    rc, out, _ = api('test -x "$QC_AGENT_ORCA_BIN" && echo OK || echo MISSING')
    check("G5 ORCA binary present and executable", "OK" in out, out)

    # ---- G6: oneAPI / entrypoint ----------------------------------------
    p = subprocess.run(
        ["docker", "compose", "logs", "--no-color", "--tail", "200", "api"],
        cwd=str(REPO), capture_output=True, text=True, timeout=60,
    )
    logs = p.stdout + p.stderr
    warned = "setvars" in logs.lower() and "warn" in logs.lower()
    check(
        "G6 entrypoint sourced oneAPI without crash-looping "
        "(a warning here is tolerated, a crash is not)",
        "Traceback" not in logs, "setvars warning present" if warned else "",
    )

    # ---- G7: read-only mounts -------------------------------------------
    # The engine mount points come from docker-compose.override.yml, which is
    # site-specific and optional (PySCF-only deployments have none of this).
    # Probe whatever ORCA path this deployment actually configured rather
    # than a hardcoded directory, and skip cleanly when no engine is mounted.
    engine_dir = os.environ.get("QC_AGENT_E2E_ENGINE_DIR", "")
    if not engine_dir:
        rc, out, _ = api("python -c \"import app.config as c; print(c.ORCA_BIN)\"")
        engine_dir = os.path.dirname(out.strip()) if rc == 0 and out.strip() else ""
    if engine_dir:
        rc, out, _ = api(f"test -d {engine_dir} && test -d /opt/intel/oneapi && echo OK || echo MISSING")
        check(f"G7a {engine_dir} and /opt/intel/oneapi mounted", "OK" in out, out)
        rc, out, _ = api(f"touch {engine_dir}/.e2e_write_probe 2>&1 && echo WRITABLE || echo READONLY")
        check(f"G7b {engine_dir} is read-only", "READONLY" in out, out)
    else:
        check("G7 engine mounts (skipped: no licensed engine configured)", True, "")

    # ---- G8: nginx serves the freshly built host dist --------------------
    # nginx bind-mounts ./frontend/dist from the HOST. docker compose build
    # does not refresh it. A hash mismatch here is the stale-UI trap.
    dist = REPO / "frontend" / "dist"
    host_bundles = sorted(p.name for p in (dist / "assets").glob("index-*.js"))
    idx = c.get("/")
    served = re.findall(r"assets/(index-[A-Za-z0-9_-]+\.js)", idx.text)
    check(
        "G8 nginx serves the host frontend/dist build actually on disk",
        bool(served) and all(s in host_bundles for s in served),
        f"served={served} on_disk={host_bundles}",
    )

    # ---- G9: lazy schema creation ---------------------------------------
    # There is no migration step: app/auth/db.py::get_pool() creates the
    # schema on first connection. Time it separately as the cold number.
    t0 = time.perf_counter()
    r = c.get("/api/auth/me")
    cold = time.perf_counter() - t0
    check(
        "G9a first auth request answers (401 unauth / 404 if auth off), not 500",
        r.status_code in (401, 404), f"{r.status_code} in {cold * 1000:.0f}ms",
    )
    check("G9b auth layer is mounted (DATABASE_URL is set)", r.status_code == 401,
          f"got {r.status_code}; 404 means QC_AGENT_DATABASE_URL is unset")
    t0 = time.perf_counter()
    c.get("/api/auth/me")
    warm = time.perf_counter() - t0
    print(f"    [perf] first auth request {cold * 1000:.0f}ms cold, {warm * 1000:.0f}ms warm")

    # ---- G10: TLS --------------------------------------------------------
    p = subprocess.run(
        ["openssl", "x509", "-in", str(REPO / "nginx/certs/intranet.crt"),
         "-noout", "-subject", "-dates"],
        capture_output=True, text=True,
    )
    check("G10 intranet TLS cert readable", p.returncode == 0, p.stdout.replace("\n", " "))

    # ---- G11: nginx forwards a port-preserving Host header ---------------
    conf = (REPO / "nginx/proxy_common.conf").read_text()
    check(
        "G11 nginx forwards Host $http_host (not $host, which strips the port "
        "and breaks the same-origin CSRF fallback on :8443)",
        "$http_host" in conf and "proxy_set_header Host $host;" not in conf,
    )

    # ---- G12: job registry reachable, and gated ------------------------
    # `c` here is an UNAUTHENTICATED client. This gate used to assert a
    # plain 200, which was true only because /api/job-registry was the one
    # route in the app with no authentication at all -- F-010. It is now
    # gated like every other route, so 401 is the correct answer to an
    # anonymous request and a 200 would mean the gap has come back.
    r = c.get("/api/job-registry")
    check("G12 [F-010] /api/job-registry is reachable but requires a session",
          r.status_code == 401, str(r.status_code),
          fail_detail="200 means the route is anonymous again; 404 means it is not mounted")

    summary()


if __name__ == "__main__":
    main()

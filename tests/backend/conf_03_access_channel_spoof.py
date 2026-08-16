"""CONF-03: app/auth/middleware.py trusts the X-Access-Channel header
completely, relying entirely on nginx to overwrite any client-supplied
value (nginx/proxy_common.conf's proxy_set_header directives strip and
replace it unconditionally). This documents -- and directly demonstrates
-- what happens if the FastAPI backend is ever reached WITHOUT going
through nginx: there is nothing at the application layer to detect that.

Reproduced from inside the `api` container itself (same network namespace
the process listens in) rather than by publishing port 8000 to the host,
which would be a real, unwanted exposure change to make just for a test.
This is equivalent to "some other route to the backend bypassing nginx" --
a misconfigured docker network, a debug port left open, etc.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from fixtures import check, summary  # noqa: E402

COMPOSE_DIR = Path(__file__).resolve().parent.parent.parent


def main() -> None:
    code = '''
import httpx
r = httpx.get("http://127.0.0.1:8000/api/health", headers={"X-Access-Channel": "intranet"})
print("direct-to-backend health check:", r.status_code)
r2 = httpx.get("http://127.0.0.1:8000/api/health")
print("direct-to-backend, no X-Access-Channel header at all:", r2.status_code, "(defaults to intranet per middleware.py line 84)")
'''
    proc = subprocess.run(
        ["docker", "compose", "exec", "-T", "api", "python", "-c", code],
        cwd=str(COMPOSE_DIR), capture_output=True, text=True, timeout=30,
    )
    print(proc.stdout)
    if proc.returncode != 0:
        print(proc.stderr, file=sys.stderr)

    check(
        "backend accepts a client-supplied X-Access-Channel: intranet header with no way to verify it came from nginx",
        "200" in proc.stdout,
        "confirms the trust boundary is nginx's proxy_set_header alone -- if the backend port is ever "
        "reachable without going through nginx (misconfigured network, debug port, container escape), "
        "any caller can claim to be on the intranet channel unconditionally",
    )
    print(
        "\nThis is an accepted infra-trust boundary, not something this test 'fixes' -- see the plan's "
        "CONF-03 note. The mitigation is deployment-level: never expose the api container's port to "
        "anything but nginx (docker-compose.yml already does this correctly via `expose:` not `ports:`)."
    )
    summary(exit_on_failure=False)


if __name__ == "__main__":
    main()

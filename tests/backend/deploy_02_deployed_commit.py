"""What scripts/update.sh believes is deployed, given what the stack reports.

The bug this covers: the script used to answer "what is running?" with
`git rev-parse HEAD`, which is the checkout's opinion and not the
deployment's. On a deployment produced by scripts/install.sh the two are the
same directory, so committing without rebuilding made the script report
"already up to date" and skip every gate it exists to enforce -- the backup,
the destructive-change report and the drain.

It now reads the commit back off the OCI revision label the Dockerfile
stamps, and off frontend/dist/.build-commit for the bundle nginx serves from
a host bind mount. The property that matters is not that it reads a label,
it is that everything it CANNOT resolve comes back empty, because every
caller reads empty as "assume stale" and a false positive here is the
original bug wearing a different hat.

Runs the real functions, lifted out of scripts/update.sh, against a stubbed
`docker` that reports whatever a case wants. Needs no stack -- putting a real
deployment into each of these states would mean rebuilding it five times.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from fixtures import COMMON_SH, check, shell_function as _extract, summary  # noqa: E402

REPO = Path(__file__).resolve().parent.parent.parent


def run(label: str, stamp: str | None, *, func: str, docker_ok: bool = True) -> str:
    """Runs one of the extracted functions with `docker` stubbed to report
    `label`, in a scratch copy of the repo's git objects so that resolving a
    sha against the checkout behaves exactly as it does for real."""
    with tempfile.TemporaryDirectory() as tmp:
        bindir = Path(tmp) / "bin"
        bindir.mkdir()
        stub = bindir / "docker"
        # `docker compose ps -q api` must print a container id for the first
        # branch to be taken at all; `docker inspect` prints the label.
        if docker_ok:
            stub.write_text(
                "#!/usr/bin/env bash\n"
                'if [ "$1" = "compose" ]; then echo deadbeefcafe; exit 0; fi\n'
                'if [ "$1" = "inspect" ]; then printf "%s\\n" ' + repr(label).replace("'", '"') + "; exit 0; fi\n"
                "exit 1\n"
            )
        else:
            # A stopped stack, or a docker that refuses the call outright.
            stub.write_text("#!/usr/bin/env bash\nexit 1\n")
        stub.chmod(0o755)

        work = Path(tmp) / "work"
        work.mkdir()
        if stamp is not None:
            (work / "frontend" / "dist").mkdir(parents=True)
            (work / "frontend" / "dist" / ".build-commit").write_text(stamp)

        script = (
            "set -euo pipefail\n"
            "COMPOSE=(docker compose -f docker-compose.yml)\n"
            'DIST_STAMP="frontend/dist/.build-commit"\n'
            f"{_extract('deployed_commit')}\n"
            f"{_extract('deployed_frontend_commit')}\n"
            f"{func}\n"
        )
        env = dict(os.environ, PATH=f"{bindir}:{os.environ['PATH']}", GIT_DIR=str(REPO / ".git"))
        # cwd is the scratch tree so the stamp file cases are isolated, while
        # GIT_DIR keeps `git rev-parse` pointed at the real object store.
        out = subprocess.run(["bash", "-c", script], capture_output=True, text=True, cwd=work, env=env)
        return out.stdout.strip()


def health_urls(compose_port_output: str) -> str:
    """The real health_urls(), with `docker compose port` stubbed to report
    whatever a deployment happens to publish.

    Lifted from scripts/lib/common.sh rather than from update.sh: install.sh
    needs the same port discovery -- it used to hardcode 127.0.0.1:8443 -- so
    the function moved into the shared library and both scripts call it there.
    It reads QC_COMPOSE, which is why this harness sets that rather than
    COMPOSE."""
    with tempfile.TemporaryDirectory() as tmp:
        bindir = Path(tmp) / "bin"
        bindir.mkdir()
        stub = bindir / "docker"
        stub.write_text(
            "#!/usr/bin/env bash\n"
            'if [ "$1" = "compose" ]; then printf "%b" ' + repr(compose_port_output).replace("'", '"') + "; exit 0; fi\n"
            "exit 1\n"
        )
        stub.chmod(0o755)
        script = (
            "set -euo pipefail\n"
            "QC_COMPOSE=(docker compose -f docker-compose.yml)\n"
            f"{_extract('health_urls', path=COMMON_SH)}\n"
            "health_urls\n"
        )
        env = dict(os.environ, PATH=f"{bindir}:{os.environ['PATH']}")
        out = subprocess.run(["bash", "-c", script], capture_output=True, text=True, cwd=tmp, env=env)
        if out.returncode != 0:
            raise RuntimeError(out.stderr)
        return out.stdout.strip()


def main() -> None:
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO, capture_output=True, text=True).stdout.strip()

    check(
        "a stamped image reports the commit it was built from",
        run(head, None, func="deployed_commit") == head,
        run(head, None, func="deployed_commit"),
    )
    check(
        "a short sha in the label is resolved to the full commit",
        run(head[:12], None, func="deployed_commit") == head,
        run(head[:12], None, func="deployed_commit"),
    )
    # The three ways of not knowing. Each must come back empty rather than
    # falling through to something that looks like an answer.
    check(
        "an image built outside this script (unknown) reports nothing",
        run("unknown", None, func="deployed_commit") == "",
        repr(run("unknown", None, func="deployed_commit")),
    )
    check(
        "an image with no label at all reports nothing",
        run("", None, func="deployed_commit") == "",
        repr(run("", None, func="deployed_commit")),
    )
    check(
        "a label naming a commit this checkout has never seen reports nothing",
        run("0" * 40, None, func="deployed_commit") == "",
        repr(run("0" * 40, None, func="deployed_commit")),
    )

    # The deployment most in need of an update is a stopped one, and update.sh
    # calls this from a `VAR="$(deployed_commit)"` assignment under `set -e`
    # with pipefail on. A pipeline that propagated docker's failure would abort
    # the update rather than answering "cannot tell".
    check(
        "a stack that is down answers 'cannot tell' instead of aborting the update",
        run("", None, func="deployed_commit", docker_ok=False) == "",
        repr(run("", None, func="deployed_commit", docker_ok=False)),
    )

    check(
        "a stamped frontend bundle reports the commit it was built from",
        run("", head, func="deployed_frontend_commit") == head,
        run("", head, func="deployed_frontend_commit"),
    )
    check(
        "a bundle with no stamp file reports nothing",
        run("", None, func="deployed_frontend_commit") == "",
        repr(run("", None, func="deployed_frontend_commit")),
    )
    check(
        "an empty stamp file reports nothing",
        run("", "\n", func="deployed_frontend_commit") == "",
        repr(run("", "\n", func="deployed_frontend_commit")),
    )

    # --- where the health check knocks -----------------------------------
    # Hardcoding 8443 made the script report a healthy stack as never having
    # come up, on a deployment whose override file remaps the port -- which
    # this project ships an example of. That verdict is not cosmetic any
    # more: it decides what --rollback will return to.
    check(
        "a remapped host port is found rather than assumed",
        health_urls("127.0.0.1:8444\n") == "https://127.0.0.1:8444",
        health_urls("127.0.0.1:8444\n"),
    )
    check(
        "a deployment published on several addresses offers loopback first",
        health_urls("127.0.0.1:8444\n100.101.102.103:8444\n")
        == "https://127.0.0.1:8444 https://100.101.102.103:8444",
        health_urls("127.0.0.1:8444\n100.101.102.103:8444\n"),
    )
    check(
        "a wildcard bind is turned into an address curl can actually connect to",
        health_urls("0.0.0.0:8443\n") == "https://127.0.0.1:8443",
        health_urls("0.0.0.0:8443\n"),
    )
    check(
        "a routable-only deployment is still reachable",
        health_urls("192.168.1.10:9443\n") == "https://127.0.0.1:9443 https://192.168.1.10:9443",
        health_urls("192.168.1.10:9443\n"),
    )
    check(
        "a stack compose cannot answer for falls back to the documented default",
        health_urls("") == "https://127.0.0.1:8443",
        health_urls(""),
    )

    summary()


if __name__ == "__main__":
    main()

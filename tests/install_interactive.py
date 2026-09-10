#!/usr/bin/env python3
"""A full interactive install, driven through the real prompts.

WHY THIS IS NOT IN tests/backend/
---------------------------------
`tests/run_backend.sh` globs `tests/backend/*.py` and runs everything it finds.
This script builds several gigabytes of images and stands a whole stack up on
port 8443, which is not something a suite run should do to a machine without
being asked. It lives here instead, run by hand:

    python3 tests/install_interactive.py /path/to/an/empty/scratch/dir

`tests/backend/install_01_static.py` and `install_02_units.py` are the ones that
run every time. They cover everything that can be checked without installing.

WHAT THIS COVERS THAT --non-interactive DOES NOT
------------------------------------------------
The scriptable mode exists partly so the installer can be tested at all, but a
mode that skips every question cannot test the questions. This drives the real
prompts on a real terminal: the numbered network menu, the certificate name
confirmation, the engine detections, the password entry with its confirmation
(which runs with terminal echo off, so it can only be exercised through a pty),
and the two questions whose answers change the host.

It answers "no" to the systemd updater question every time. Answering yes would
write a real user unit onto whatever machine this runs on.

WHAT IT DELIBERATELY DOES NOT COVER
-----------------------------------
The "docker daemon is not running" preflight. Verifying it means stopping the
daemon, and on a shared machine that interrupts everyone else's containers. The
message it prints is exercised by reading, not by running.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import check, summary  # noqa: E402

try:
    import pexpect
except ImportError:
    raise SystemExit("this script needs pexpect: conda activate qc-agent")

REPO = Path(__file__).resolve().parent.parent
ADMIN = {
    "email": "qatest_admin@example.invalid",
    "username": "qatest_admin",
    "first": "QA",
    "last": "Test",
    "password": "interactive-install-pw-2026",
}


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit(f"usage: {sys.argv[0]} <empty scratch directory>")
    target = Path(sys.argv[1]).resolve()
    if target.exists() and any(target.iterdir()):
        raise SystemExit(f"{target} is not empty -- refusing to install over it")

    subprocess.run(["git", "clone", "--quiet", str(REPO), str(target)], check=True)

    # `git clone` of a local path clones the committed HEAD, not the working
    # tree, so uncommitted edits to the very script under test are invisible to
    # it. That is not a hypothetical: the first run of this driver failed, the
    # fix was made, and the second run failed identically because the clone
    # still held the old code. Anything modified but not yet committed is copied
    # over the clone, and named, so a pass is a pass for the code you are
    # actually editing.
    dirty = subprocess.run(
        ["git", "-C", str(REPO), "status", "--porcelain", "--untracked-files=no"],
        capture_output=True, text=True, check=True,
    ).stdout.splitlines()
    overlaid = []
    for line in dirty:
        rel = line[3:].split(" -> ")[-1].strip()
        src = REPO / rel
        if src.is_file():
            dst = target / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(src.read_bytes())
            dst.chmod(src.stat().st_mode & 0o777)
            overlaid.append(rel)
    if overlaid:
        print(f"  .. testing {len(overlaid)} uncommitted file(s) copied over the clone:")
        for rel in overlaid:
            print(f"       {rel}")

    # A generous timeout on every expect: the build alone is minutes, and this
    # runs on whatever the machine happens to be doing at the time.
    child = pexpect.spawn(
        "bash", ["scripts/install.sh"], cwd=str(target), encoding="utf-8", timeout=1800,
        env=dict(os.environ, TERM="dumb"),
    )
    transcript: list[str] = []
    child.logfile_read = type("T", (), {"write": transcript.append, "flush": lambda s: None})()
    log = target / "interactive-install.log"

    def keep() -> str:
        """Write the transcript out. Called on every exit path, successful or
        not: the first run of this driver failed before the engine prompt and
        discarded everything it had seen, which is the one moment the record is
        actually needed."""
        text = "".join(transcript)
        log.write_text(text)
        return text

    import atexit
    atexit.register(keep)

    def answer(pattern: str, reply: str, label: str) -> bool:
        try:
            child.expect(pattern)
        except (pexpect.TIMEOUT, pexpect.EOF) as exc:
            print(keep()[-3000:])
            raise SystemExit(
                f"the installer never asked {label!r} "
                f"({type(exc).__name__} waiting for {pattern!r}); transcript at {log}"
            )
        child.sendline(reply)
        return True

    # Step 2. The one question that can end the install before it starts.
    answer(r"Continue installing here\? \[Y/n\]", "y", "whether to install here")

    # Step 4. One numbered menu, in place of the three yes/no questions this
    # used to ask. 1 is always "this machine only" and is always offered.
    answer(r"Choose 1-\d", "1", "where it should be reachable")

    # The certificate name, derived and shown for approval rather than assumed.
    answer(r"Press enter to accept, or type the name to use:", "", "the certificate name")

    # Steps 5. Whatever this host has. Both engines are optional, and the
    # prompts differ depending on what was found, so each is matched loosely.
    try:
        idx = child.expect([r"Found orca at .* -- use it\?", r"Enter a orca path manually\?"])
    except (pexpect.TIMEOUT, pexpect.EOF) as exc:
        print(keep()[-3000:])
        raise SystemExit(f"never reached the ORCA question: {type(exc).__name__}; transcript at {log}")
    child.sendline("y" if idx == 0 else "n")
    idx = child.expect([r"Found BAGEL at .* -- use it\?", r"Enter a BAGEL path manually\?"])
    child.sendline("y" if idx == 0 else "n")
    # oneAPI is found automatically when it is present; only asked for if not.
    idx = child.expect([r"Install it\? \[y/N\]", r"enter its path\?"])
    if idx == 1:
        child.sendline("n")
        child.expect(r"Install it\? \[y/N\]")
    child.sendline("n")  # block2: 379 MB, and this is a test install

    # Step 6 asks nothing when the model is already pulled, and only warns when
    # no server answers, so there is no prompt to match here either way.

    # Steps 7 and 8 are the long ones. Nothing to answer; wait for the account.
    try:
        child.expect(r"Email: ", timeout=2400)
    except (pexpect.TIMEOUT, pexpect.EOF) as exc:
        print("".join(transcript)[-4000:])
        raise SystemExit(f"never reached the admin prompt: {type(exc).__name__}")
    child.sendline(ADMIN["email"])
    answer(r"Username: ", ADMIN["username"], "the admin username")
    answer(r"First name: ", ADMIN["first"], "the admin first name")
    answer(r"Last name: ", ADMIN["last"], "the admin last name")

    # The password pair runs with terminal echo off. Getting it wrong on purpose
    # first proves the mismatch branch re-asks rather than accepting either one.
    child.expect(r"Password \(at least 8 characters\): ")
    child.sendline(ADMIN["password"])
    child.expect(r"Confirm password: ")
    child.sendline(ADMIN["password"] + "-typo")
    idx = child.expect([r"those did not match", r"Install it\? \[Y/n\]"])
    check(
        "a mismatched password confirmation is caught and re-asked",
        idx == 0,
        "asked again rather than accepting either of the two",
        "the installer moved on with two different passwords",
    )
    if idx == 0:
        child.expect(r"Password \(at least 8 characters\): ")
        child.sendline(ADMIN["password"])
        child.expect(r"Confirm password: ")
        child.sendline(ADMIN["password"])

    # Step 10. NO. This writes a systemd user unit onto the host.
    answer(r"Install it\? \[Y/n\]", "n", "whether to install the updater service")

    child.expect(pexpect.EOF, timeout=600)
    child.close()
    out = keep()

    check(
        "the interactive install finishes successfully",
        child.exitstatus == 0,
        f"exit {child.exitstatus}",
        out[-3000:],
    )
    check(
        "it ends by saying the deployment is up",
        "NexusQC is up." in out,
        "the closing summary was printed",
        out[-1500:],
    )
    check(
        "it names an address to open",
        "https://127.0.0.1:8443" in out,
        "https://127.0.0.1:8443",
        out[-1500:],
    )
    check(
        "the admin account was created through the prompts",
        f"admin account created: {ADMIN['username']}" in out,
        "created",
        out[-1500:],
    )
    check(
        "the updater service was declined and nothing was installed on the host",
        "skipped -- install it later" in out,
        "declined",
        out[-1500:],
    )
    check(
        "the password never appears in the output, even echoed back",
        ADMIN["password"] not in out,
        "absent from the whole transcript",
    )
    check(
        "the step counter never exceeds its own total",
        not any(
            f"[{n}/" in out and f"[{n}/{t}]" in out and n > int(t)
            for n, t in [(11, "10"), (12, "10")]
        )
        and "[11/10]" not in out,
        "no step numbered past the total",
        out[-1500:],
    )

    print(f"\ntranscript kept at: {log}")
    summary()


if __name__ == "__main__":
    main()

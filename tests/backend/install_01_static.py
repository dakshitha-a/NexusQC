"""scripts/install.sh, checked without installing anything.

WHY THIS EXISTS
---------------
install.sh is the entrypoint: for most people it is the only NexusQC code they
will ever watch run. Until this script existed, nothing anywhere exercised it.
There is no CI in this repository, no shellcheck runner, and not even a
`bash -n`. The only evidence the installer worked was a sentence in
docs/DEPLOYMENT.md recording that somebody had once run it by hand.

An installer is also the hardest thing in the repository to test properly,
because a real run builds several gigabytes of images and stands up a stack.
Everything here is what can be checked in under a second and would still have
caught a real defect:

  - it parses at all, under both shells that will ever execute part of it;
  - the prologue -- the only part that comes off a `curl | sh` pipe -- is
    strictly POSIX, because a bashism there kills the one-liner on every
    Debian-family machine, which is most of them;
  - every refusal path refuses, with a message that names what to do instead;
  - --help answers without putting a repository on anyone's disk;
  - the documented prerequisites are the ones the script actually enforces.

That last one is a doc-drift check with a real history: README listed Ollama as
a prerequisite, which the installer only ever warns about, and omitted openssl
and curl, which it hard-requires.

Needs no stack, and nothing here starts a container. Runs anywhere bash and
dash are present, like the deploy_0* scripts.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from fixtures import check, summary  # noqa: E402

REPO = Path(__file__).resolve().parent.parent.parent
INSTALL = REPO / "scripts" / "install.sh"
COMMON = REPO / "scripts" / "lib" / "common.sh"
UPDATE = REPO / "scripts" / "update.sh"
CERT = REPO / "scripts" / "gen_intranet_cert.sh"


def run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def strip_comments(text: str) -> str:
    """Whole-line comments removed, so a scan reads code rather than prose.

    Both scans below need this and for the same reason. The prologue's header
    explains at length which bashisms are forbidden and names every one of
    them; the disk-headroom check's comment names `node:24-slim` and its size
    while explaining where the 12 GB figure comes from. Scanning the raw text
    finds each of those and calls it a violation of the rule the comment is
    there to state.
    """
    return "\n".join(
        line for line in text.splitlines() if not line.lstrip().startswith("#")
    )


def prologue() -> str:
    """Everything above the `exec bash`, i.e. everything a pipe ever runs.

    Located rather than hardcoded as a line number: the prologue has grown
    before and the two documents that quote its length were both stale by a
    factor of four when this was written.
    """
    text = INSTALL.read_text()
    marker = 'exec bash "$0" "$@"'
    idx = text.index(marker)
    return text[: idx + len(marker)]


def main() -> None:
    # --- it parses -----------------------------------------------------------
    for path in (INSTALL, COMMON, UPDATE, CERT):
        r = run(["bash", "-n", str(path)])
        check(
            f"{path.relative_to(REPO)} parses under bash",
            r.returncode == 0,
            "no syntax errors",
            r.stderr.strip(),
        )

    # --- the prologue is POSIX ----------------------------------------------
    head = prologue()
    n_lines = head.count("\n") + 1
    if shutil.which("dash"):
        with tempfile.NamedTemporaryFile("w", suffix=".sh", delete=False) as fh:
            fh.write(head)
            tmp = fh.name
        try:
            r = run(["dash", "-n", tmp])
            check(
                f"the {n_lines}-line prologue parses under dash, which is /bin/sh on "
                "Debian and Ubuntu",
                r.returncode == 0,
                f"{n_lines} lines, POSIX-clean",
                r.stderr.strip(),
            )
        finally:
            Path(tmp).unlink(missing_ok=True)

    # A belt-and-braces read of the same constraint. `dash -n` catches syntax,
    # but several bashisms are syntactically valid POSIX and merely behave
    # differently, so they parse and then misbehave on the machines that matter.
    #
    # Comment lines are dropped first, and that is not a convenience: the
    # prologue's own header explains at length which bashisms are forbidden and
    # names every one of them, so a scan of the raw text finds `[[`, `$'` and
    # `BASH_SOURCE` in the very prose telling you not to write them.
    code = strip_comments(head)
    bashisms = {
        "[[ ]] test": r"\[\[",
        "array assignment": r"^\s*\w+=\(",
        "$'...' quoting": r"\$'",
        "${BASH_SOURCE}": r"BASH_SOURCE",
        "set -o pipefail": r"set -o pipefail",
        "here-string": r"<<<",
    }
    for label, pattern in bashisms.items():
        found = re.search(pattern, code, re.M)
        check(
            f"the prologue uses no {label}",
            found is None,
            "absent, so `curl | sh` survives dash",
            f"found: {found.group(0) if found else ''}",
        )

    # --- --help answers, and installs nothing --------------------------------
    if shutil.which("dash"):
        with tempfile.TemporaryDirectory() as tmp:
            # Piped exactly the way the README tells people to run it, so this
            # covers the real pipe path rather than a bash invocation of a file.
            r = subprocess.run(
                ["dash", "-s", "--", "--help"],
                input=INSTALL.read_text(),
                capture_output=True,
                text=True,
                cwd=tmp,
                env=dict(os.environ, HOME=tmp),
            )
            check(
                "--help through a real `sh` pipe prints usage and exits 0",
                r.returncode == 0 and "usage: install.sh" in r.stdout,
                f"exit {r.returncode}, {len(r.stdout.splitlines())} lines of usage",
                r.stderr.strip(),
            )
            # Printing usage is not a reason to put a repository on someone's
            # disk, which is why the --help scan sits above the clone.
            check(
                "--help through the pipe clones nothing",
                not (Path(tmp) / "apps").exists(),
                "no ~/apps/NexusQC created",
                str(list(Path(tmp).iterdir())),
            )
            check(
                "--help documents --non-interactive and the admin variables it needs",
                "--non-interactive" in r.stdout and "NEXUSQC_ADMIN_PASSWORD" in r.stdout,
                "both present",
            )

    # --- every refusal refuses, and says what to do instead ------------------
    # Each of these runs the real script. All of them exit before step 1, so
    # nothing is read, written or started in this checkout.
    refusals = [
        (
            "no terminal and no --non-interactive is refused, naming the alternative",
            [],
            {},
            ["--non-interactive", "no terminal"],
        ),
        (
            "--non-interactive without --bind is refused, naming --bind",
            ["--non-interactive"],
            {},
            ["--bind"],
        ),
        (
            "--non-interactive names the missing admin variable rather than failing vaguely",
            ["--non-interactive", "--bind=localhost"],
            {},
            ["NEXUSQC_ADMIN_EMAIL"],
        ),
        (
            "an unknown option is refused",
            ["--nope"],
            {},
            ["unknown option"],
        ),
        (
            "an unknown --bind mode is refused, listing the valid ones",
            ["--bind=everywhere"],
            {},
            ["localhost", "lan", "tailscale", "both"],
        ),
    ]
    for label, args, extra_env, expected in refusals:
        r = subprocess.run(
            ["bash", str(INSTALL), *args],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            cwd=REPO,
            env=dict(os.environ, **extra_env),
        )
        out = r.stdout + r.stderr
        missing = [e for e in expected if e not in out]
        check(
            label,
            r.returncode != 0 and not missing,
            f"exit {r.returncode}: {out.strip().splitlines()[0] if out.strip() else '(silent)'}",
            f"missing from the message: {missing}",
        )

    # A password given as an environment variable must not be echoed back. It is
    # the one value here that would end up in a CI log verbatim.
    r = subprocess.run(
        ["bash", str(INSTALL), "--non-interactive", "--bind=localhost"],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        cwd=REPO,
        env=dict(
            os.environ,
            NEXUSQC_ADMIN_EMAIL="a@b.co",
            NEXUSQC_ADMIN_USERNAME="u",
            NEXUSQC_ADMIN_FIRSTNAME="F",
            NEXUSQC_ADMIN_LASTNAME="L",
            NEXUSQC_ADMIN_PASSWORD="short",
        ),
    )
    out = r.stdout + r.stderr
    check(
        "a too-short admin password is refused without printing the password",
        r.returncode != 0 and "at least 8" in out and "short" not in out,
        f"exit {r.returncode}, password absent from output",
        out.strip(),
    )

    # --- the frontend is never built on the host -----------------------------
    # A host Node build was deleted deliberately: it produced a second artefact
    # from the same source, only one of which was deployed, and its no-npm
    # fallback ran a container as root and left root-owned files behind.
    text = INSTALL.read_text()
    install_code = strip_comments(text)
    for forbidden in ("npm ci", "npm run build", "node:24"):
        check(
            f"install.sh does not build the frontend on the host ({forbidden!r})",
            forbidden not in install_code,
            "absent from the code; the bundle is copied out of the api image",
        )

    # --- colour is guarded ---------------------------------------------------
    # install.sh alone among its siblings used to define colours unconditionally,
    # so an install redirected to a log file -- the normal way someone captures
    # one to send you -- was full of escape sequences.
    check(
        "install.sh does not define colour codes of its own",
        not re.search(r"^RED=\$'", text, re.M),
        "they come from lib/common.sh, which guards on [ -t 1 ]",
    )
    r = subprocess.run(
        ["bash", "-c", f"source {COMMON}; printf '%s' \"$RED$GRN$BLD\""],
        capture_output=True,
        text=True,
    )
    check(
        "sourced with stdout redirected, the colour codes are empty",
        r.stdout == "",
        f"{len(r.stdout)} bytes of escape sequences",
        repr(r.stdout),
    )

    # --- the documented prerequisites are the enforced ones ------------------
    # H5 in the audit: README listed Ollama, which is only ever a warning, and
    # omitted openssl and curl, which are hard requirements.
    m = re.search(r"^require_tools (.+)$", text, re.M)
    required = m.group(1).split() if m else []
    check(
        "install.sh states its required tools in one place",
        len(required) >= 3,
        f"require_tools {' '.join(required)}",
    )
    readme = (REPO / "README.md").read_text()
    install_section = readme[readme.index("## Install") :][:4000]
    undocumented = [t for t in required if t not in install_section]
    check(
        "README's install section names every tool install.sh requires",
        not undocumented,
        f"documented: {' '.join(required)}",
        f"required by the script but not named in README: {undocumented}",
    )

    # --- shellcheck, when it is available ------------------------------------
    if shutil.which("shellcheck"):
        r = run(["shellcheck", "-x", str(INSTALL), str(COMMON), str(UPDATE), str(CERT)])
        check(
            "shellcheck reports nothing on the installer and its library",
            r.returncode == 0,
            "clean",
            r.stdout.strip()[:2000],
        )
    else:
        # Not installed on every host, and not worth making a hard dependency of
        # the suite. The container form is in docs/TESTING.md.
        print("  .. shellcheck not on PATH; skipping that check")

    summary()


if __name__ == "__main__":
    main()

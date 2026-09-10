"""The installer's helper functions, against input designed to break them.

WHY THESE FUNCTIONS AND NOT OTHERS
----------------------------------
scripts/lib/common.sh holds the pieces install.sh and update.sh share. Three of
them are here because each had a defect that produced no error at all -- the
worst kind an installer can have, because the person running it has no idea
anything went wrong:

  envset       escaped `#` for its sed delimiter and nothing else. A value
               containing `&` -- which sed reads in a replacement as "the whole
               match" -- was silently rewritten, and one containing `|` broke
               the other branch's delimiter. The result is a corrupted .env, not
               a failure.
  valid_ipv4   did not exist. A hostname typed at the installer's "IP address:"
               prompt went into the certificate's subjectAltName as
               `IP:<hostname>`, openssl refused it, gen_intranet_cert.sh had its
               stderr discarded, and the install ended with no output at all.
  ask / ask_yn were bare `read` calls. Under `set -e`, end of input -- Ctrl-D, a
               closed terminal, a pipe that ran dry -- exited the installer
               mid-question in silence.

Unlike the deploy_0* scripts, which lift single functions out of update.sh with
fixtures.shell_function, this one sources the library outright. That is the
difference between the two files: update.sh wraps its whole body in main() and
cannot be sourced, whereas common.sh exists to be sourced and is sourced the
same way here as install.sh sources it. Testing it any other way would be
testing something the installer does not do.

Needs no stack and starts no container.
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from fixtures import check, summary  # noqa: E402

REPO = Path(__file__).resolve().parent.parent.parent
COMMON = REPO / "scripts" / "lib" / "common.sh"


def sh(body: str, stdin: str = "", cwd: str | None = None) -> subprocess.CompletedProcess:
    """Run `body` with the real library sourced, exactly as install.sh does."""
    return subprocess.run(
        ["bash", "-c", f"set -euo pipefail\nsource {COMMON}\n{body}"],
        input=stdin,
        capture_output=True,
        text=True,
        cwd=cwd,
    )


def envset_roundtrip(initial: str, key: str, value: str) -> tuple[str, str]:
    """Set `key` to `value` in a .env holding `initial`; return (file, readback).

    The readback matters more than the file text: the whole point is that what
    a later run reads is byte-for-byte what the installer meant to write.
    """
    with tempfile.TemporaryDirectory() as tmp:
        Path(tmp, ".env").write_text(initial)
        r = sh(
            f"envset {key} {shell_quote(value)}\n"
            f"printf '%s' \"$(envget .env {key})\"",
            cwd=tmp,
        )
        if r.returncode != 0:
            raise RuntimeError(r.stderr)
        return Path(tmp, ".env").read_text(), r.stdout


def shell_quote(s: str) -> str:
    return "'" + s.replace("'", "'\\''") + "'"


def main() -> None:
    # --- envset --------------------------------------------------------------
    # Every character here has a meaning to sed. `&` is the one that actually
    # bit: a value containing it came back with the matched text spliced in.
    nasty = "p@ss&word|with#hash\\and\\backslash"
    text, readback = envset_roundtrip("QC_A=old\n", "QC_A", nasty)
    check(
        "a value containing & | # and \\ survives envset unchanged",
        readback == nasty,
        f"read back exactly: {readback}",
        f"wrote {readback!r}, meant {nasty!r}",
    )

    # The second branch: .env.example ships most keys commented out as examples,
    # and a value the installer fills in must replace the example rather than
    # leaving both the placeholder and the real value in the file.
    text, readback = envset_roundtrip(
        "# QC_AGENT_ORCA_BIN=/opt/orca/orca\n", "QC_AGENT_ORCA_BIN", "/usr/local/orca6/orca"
    )
    check(
        "a commented-out example is replaced in place, not left beside the real value",
        readback == "/usr/local/orca6/orca" and "# QC_AGENT_ORCA_BIN" not in text,
        f"file now reads: {text.strip()}",
        f"file: {text!r}",
    )

    text, readback = envset_roundtrip("QC_OTHER=keep\n", "QC_NEW", "value")
    check(
        "an absent key is appended without disturbing the rest of the file",
        readback == "value" and "QC_OTHER=keep" in text,
        f"file now reads: {text.strip().replace(chr(10), ' / ')}",
    )

    text, _ = envset_roundtrip("QC_A=1\nQC_B=2\nQC_C=3\n", "QC_B", "two")
    check(
        "setting one key rewrites only that key's line",
        text == "QC_A=1\nQC_B=two\nQC_C=3\n",
        f"{text!r}",
    )

    # A generated secret is the common case and must be exact -- a mangled JWT
    # secret produces logins that fail with no explanation.
    secret = "a3f" * 20
    _, readback = envset_roundtrip("QC_AGENT_JWT_SECRET=change-me\n", "QC_AGENT_JWT_SECRET", secret)
    check(
        "a generated hex secret round-trips exactly",
        readback == secret,
        f"{len(readback)} characters, identical",
    )

    # --- valid_ipv4 ----------------------------------------------------------
    valid = ["127.0.0.1", "192.168.1.50", "10.0.0.1", "100.64.0.9", "255.255.255.255", "0.0.0.0"]
    invalid = [
        "lab-host.example.edu",  # the case that killed the install in silence
        "localhost",
        "1.2.3",
        "1.2.3.4.5",
        "256.1.1.1",
        "1.2.3.",
        ".1.2.3",
        "1..2.3",
        "",
        "192.168.1.50 ",
        "2001:db8::1",  # IPv6: the SAN needs IP: entries openssl can parse as v4
    ]
    r = sh(
        "for v in "
        + " ".join(shell_quote(v) for v in valid)
        + '; do valid_ipv4 "$v" || echo "REJECTED $v"; done'
    )
    check(
        f"all {len(valid)} real IPv4 addresses are accepted",
        r.returncode == 0 and r.stdout.strip() == "",
        "including 0.0.0.0 and 255.255.255.255",
        r.stdout.strip(),
    )
    wrongly_accepted = []
    for v in invalid:
        r = sh(f'if valid_ipv4 {shell_quote(v)}; then echo yes; else echo no; fi')
        if r.stdout.strip() == "yes":
            wrongly_accepted.append(v)
    check(
        f"all {len(invalid)} non-addresses are rejected, hostnames included",
        not wrongly_accepted,
        "a hostname at the IP prompt is now caught before openssl sees it",
        f"wrongly accepted: {wrongly_accepted}",
    )

    # --- ask / ask_yn --------------------------------------------------------
    r = sh('ask_yn "Proceed?" y; echo "ANSWER=$ASK_YN_OK"', stdin="\n")
    check(
        "an empty answer takes the default",
        "ANSWER=1" in r.stdout,
        r.stdout.strip(),
        r.stdout + r.stderr,
    )
    for reply, expected in [("y", 1), ("Y", 1), ("yes", 1), ("n", 0), ("N", 0), ("no", 0)]:
        r = sh('ask_yn "Proceed?" y; echo "ANSWER=$ASK_YN_OK"', stdin=f"{reply}\n")
        check(
            f"{reply!r} is read as {'yes' if expected else 'no'}",
            f"ANSWER={expected}" in r.stdout,
            r.stdout.strip(),
            r.stdout + r.stderr,
        )
    # An unrecognised answer must not be silently taken as the default. The
    # default here is `y`, so guessing would mean "maybe" installs something.
    r = sh('ask_yn "Proceed?" y; echo "ANSWER=$ASK_YN_OK"', stdin="maybe\nn\n")
    check(
        "an answer that is neither yes nor no is asked again, not guessed",
        "ANSWER=0" in r.stdout and "please answer y or n" in (r.stdout + r.stderr),
        r.stdout.strip(),
        r.stdout + r.stderr,
    )

    # The silent-death case. Under `set -e` a bare `read` at end of input killed
    # the installer with no output whatsoever.
    r = sh('ask_yn "Proceed?" y; echo "REACHED_HERE"', stdin="")
    out = r.stdout + r.stderr
    check(
        "end of input at a yes/no question fails loudly instead of exiting in silence",
        r.returncode != 0 and "REACHED_HERE" not in r.stdout and "end of file" in out,
        f"exit {r.returncode}: {out.strip().splitlines()[0] if out.strip() else '(silent)'}",
        out,
    )
    r = sh('ask "Name: "; echo "REACHED_HERE"', stdin="")
    out = r.stdout + r.stderr
    check(
        "end of input at a free-text question does the same",
        r.returncode != 0 and "REACHED_HERE" not in r.stdout and "end of file" in out,
        f"exit {r.returncode}: {out.strip().splitlines()[0] if out.strip() else '(silent)'}",
        out,
    )
    r = sh('ask "Hostname: " "lab.example.edu"; echo "GOT=$REPLY"', stdin="\n")
    check(
        "a free-text question with a default accepts it on a bare enter",
        "GOT=lab.example.edu" in r.stdout,
        r.stdout.strip(),
        r.stdout + r.stderr,
    )

    # --- step numbering ------------------------------------------------------
    # The counter exists because the script emitted sixteen unnumbered banners
    # and four documents disagreed about how many steps there were.
    r = sh('QC_STEP_TOTAL=3; step "one"; step "two"; step "three"')
    banners = [ln for ln in r.stdout.splitlines() if ln.startswith("---")]
    check(
        "steps number themselves against the declared total",
        [b.split()[1] for b in banners] == ["[1/3]", "[2/3]", "[3/3]"],
        " ".join(b.split()[1] for b in banners),
        r.stdout,
    )
    check(
        "every banner is the same width regardless of title length",
        len({len(b) for b in banners}) == 1,
        f"all {len(banners)} banners are {len(banners[0])} characters",
        str([len(b) for b in banners]),
    )
    r = sh('step "unnumbered"')
    check(
        "with no declared total the counter stays out of the way",
        "[" not in r.stdout.splitlines()[1],
        r.stdout.strip().splitlines()[-1],
    )

    summary()


if __name__ == "__main__":
    main()

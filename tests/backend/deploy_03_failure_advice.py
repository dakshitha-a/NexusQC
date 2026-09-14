"""What scripts/update.sh tells an operator to do when an update goes wrong,
and what it writes down about one that did not come up.

Both of these were the same mistake in two places. `--rollback` moves code
and nothing else, so it is the right answer for exactly one situation: a
change the impact report did not call destructive, on a deployment whose
checkout actually moved. It used to be printed on every failure path,
including after a destructive update, where following it leaves the old code
running against an already-migrated database. And the `updated` line was
appended to .update-log before the health check had been considered, so a
deployment that never came up was recorded exactly like one that did.

Advice is not decoration here: it is read by someone whose deployment is
already broken, which is the worst moment to be handed an instruction that
cannot work. So this asserts the three branches say the right thing, and in
particular that the two where --rollback cannot help do not mention it as
the thing to do.

Runs the real functions, lifted out of scripts/update.sh. Needs no stack.
"""
from __future__ import annotations

import re
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from fixtures import check, shell_function, summary  # noqa: E402

BACKUP_DIR = "/tmp/nexusqc-backups/20260828-140000"


def _run(script: str, cwd: str) -> str:
    out = subprocess.run(["bash", "-c", script], capture_output=True, text=True, cwd=cwd)
    if out.returncode != 0:
        raise RuntimeError(out.stderr)
    return out.stdout


def advice(*, destructive: int, rebuild_only: int, backup: str = BACKUP_DIR) -> str:
    script = (
        "set -uo pipefail\n"
        "YEL=''; RST=''\n"
        f'DESTRUCTIVE={destructive}\nREBUILD_ONLY={rebuild_only}\nBACKUP_PATH="{backup}"\n'
        'UPDATE_LOG=".update-log"\nTARGET_SHA="ccc"\n'
        f"{shell_function('recovery_advice')}\n"
        "recovery_advice\n"
    )
    with tempfile.TemporaryDirectory() as tmp:
        return _run(script, tmp)


def record(*, verb: str, rebuild_only: int) -> list[str]:
    # PREVIOUS_SHA and CHECKOUT_SHA are deliberately different here. They
    # differ in real life exactly when this work is doing its job: with a
    # stamped image running behind the checkout, HEAD has moved to a commit
    # that was never deployed, and the log has to name the one that actually
    # ran. REPORT_FROM is set too, and to something else, to prove the log
    # takes the rollback target and not the report's baseline: after a history
    # rewrite the deployed commit is off the branch, the report is still
    # measured from it, and a rollback must not go there.
    script = (
        "set -uo pipefail\n"
        f'REBUILD_ONLY={rebuild_only}\nUPDATE_LOG=".update-log"\n'
        'TARGET_SHA="ccc"\nCHECKOUT_SHA="never-deployed"\nPREVIOUS_SHA="was-deployed"\n'
        'REPORT_FROM="off-the-branch"\n'
        "info() { :; }\n"
        f"{shell_function('record_update')}\n"
        f"record_update {verb}\n"
        'cat "$UPDATE_LOG" 2>/dev/null || true\n'
    )
    with tempfile.TemporaryDirectory() as tmp:
        return [ln for ln in _run(script, tmp).splitlines() if ln.strip()]


def main() -> None:
    # --- the advice -------------------------------------------------------
    plain = advice(destructive=0, rebuild_only=0)
    check(
        "an ordinary failed update is told to roll the code back",
        "scripts/update.sh --rollback" in plain,
        plain.strip().replace("\n", " | "),
    )
    check(
        "and is told where its backup went, in every case",
        all(BACKUP_DIR in advice(destructive=d, rebuild_only=r)
            for d, r in ((0, 0), (1, 0), (0, 1))),
        "one of the three branches omitted the backup directory",
    )

    destructive = advice(destructive=1, rebuild_only=0)
    check(
        "a destructive update is sent to restore.sh, not to --rollback",
        "scripts/restore.sh" in destructive and f"scripts/restore.sh {BACKUP_DIR}" in destructive,
        destructive.strip().replace("\n", " | "),
    )
    check(
        "and --rollback is named only to say not to use it",
        not re.search(r"^\s*scripts/update\.sh --rollback\s*$", destructive, re.M),
        "the destructive branch offered --rollback as an instruction",
    )

    rebuild = advice(destructive=0, rebuild_only=1)
    check(
        "a rebuild-only update says --rollback has nothing to return to",
        "cannot help here" in rebuild and "never moved" in rebuild,
        rebuild.strip().replace("\n", " | "),
    )
    check(
        "and does not offer it as an instruction either",
        not re.search(r"^\s*scripts/update\.sh --rollback\s*$", rebuild, re.M),
        "the rebuild-only branch offered --rollback as an instruction",
    )

    # An operator with no backup path still has to be told something useful,
    # since this runs at the moment the deployment is already broken.
    empty = advice(destructive=1, rebuild_only=0, backup="")
    check(
        "with no captured backup path it still points at where backup.sh reported",
        "scripts/backup.sh" in empty,
        empty.strip().replace("\n", " | "),
    )

    # --- what gets written down -------------------------------------------
    healthy = record(verb="updated", rebuild_only=0)
    check(
        "a healthy update is recorded with the verb --rollback trusts",
        healthy and healthy[-1].split()[0] == "updated",
        str(healthy),
    )
    check(
        "the previous commit recorded is the one that was DEPLOYED, not where HEAD sat",
        healthy and healthy[-1].split()[2:] == ["ccc", "was-deployed"],
        f"{healthy} -- rolling back to a commit that was never deployed is the same "
        "class of mistake as rolling back to one that never came up healthy",
    )
    unhealthy = record(verb="unhealthy", rebuild_only=0)
    check(
        "one that did not come up is recorded as unhealthy, not as a new baseline",
        unhealthy and unhealthy[-1].split()[0] == "unhealthy",
        str(unhealthy),
    )
    check(
        "a rebuild-only update writes nothing, since it would name one commit twice",
        record(verb="updated", rebuild_only=1) == [],
        str(record(verb="updated", rebuild_only=1)),
    )

    summary()


if __name__ == "__main__":
    main()

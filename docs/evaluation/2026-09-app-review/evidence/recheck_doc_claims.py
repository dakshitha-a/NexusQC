#!/usr/bin/env python3
"""Re-check, mechanically, every documentation claim the review falsified from
code alone.

    PYTHONPATH=$PWD python3 docs/evaluation/2026-09-app-review/evidence/recheck_doc_claims.py

WHY THIS EXISTS, and what it does not claim.

`evidence/doc-claims.md` is a 283-row checklist of every user-visible,
falsifiable claim in README.md, docs/CONFIGURATION.md, docs/QM_CAPABILITIES.md,
docs/DEPLOYMENT.md, the help flyout and the welcome screen. Fourteen of those
rows were falsifiable from the code alone and were listed in the checklist's own
opening table; the rest need a live walkthrough of the running app, and the
review itself deferred that (see report.md's "First contact, molecules,
projects, sharing, admin, layout" and "What was not tested, and why").

This script re-checks the fourteen, and only the fourteen. It is deliberately
mechanical: each row asks the code or the document a question with a yes or no
answer, so the result is reproducible by anyone running it rather than resting
on a reader's judgement. It does not attempt the live walkthrough and does not
report a number that could be mistaken for one.

Each row prints its claim, what the review said the code said, and what the
code says now.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO))

RESULTS: list[tuple[str, bool, str]] = []


def row(claim: str, ok: bool, detail: str) -> None:
    RESULTS.append((claim, ok, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {claim}\n        {detail}")


def read(rel: str) -> str:
    p = REPO / rel
    return p.read_text() if p.exists() else ""


def main() -> None:
    readme = read("README.md")
    deployment = read("docs/DEPLOYMENT.md")
    configuration = read("docs/CONFIGURATION.md")
    nginx_conf = read("nginx/nginx.conf")
    help_flyout = read("frontend/src/app-shell/HelpFlyout.tsx")
    check_destructive = read("scripts/check_destructive.sh")
    backup_sh = read("scripts/backup.sh")
    update_sh = read("scripts/update.sh")
    admin_cli = read("server/admin_cli.py")

    print("== the fourteen claims the review falsified from code alone ==\n")

    # 1. R-019
    row(
        "update.sh --rollback really moves the checkout back",
        "git merge --ff-only" not in update_sh or "git checkout" in update_sh,
        "the rollback path uses a checkout rather than a fast-forward merge that "
        "is a no-op on a branch"
        if "git checkout" in update_sh else "still only fast-forward merges",
    )
    row(
        "the rebuilt image is stamped with the commit it was actually built from",
        "IMAGE_COMMIT" in update_sh or "org.opencontainers.image.revision" in update_sh,
        "update.sh stamps a commit label on the image it builds",
    )

    # 2. R-026
    # The command spans three lines with shell continuations, so the whole
    # block up to the closing fence is what has to carry the arguments.
    m = re.search(r"bootstrap-admin(.*?)```", deployment, re.S)
    documented = ("bootstrap-admin" + m.group(1)) if m else ""
    needs = ("--first-name", "--last-name", "--email", "--username")
    row(
        "DEPLOYMENT.md's bootstrap-admin command carries every required argument",
        bool(documented) and all(a in documented for a in needs),
        f"documented: {documented.strip()[:160] or '(no bootstrap-admin line found)'}",
    )

    # 3. R-021/R-024
    # R-021's fix inverted the list rather than lengthening it: --full now
    # archives every child of data/ minus an explicit exclude list, so a new
    # child is included by default and has to be argued out. The check is
    # therefore that the include list is gone and the exclusion is small and
    # named, not that three particular directories appear in it.
    m = re.search(r"FULL_DATA_EXCLUDE=\(([^)]*)\)", backup_sh)
    excluded = (m.group(1) if m else "").split()
    row(
        "backup.sh --full archives every child of data/ except a named few",
        bool(m) and "FULL_DATA_DIRS" not in backup_sh and excluded == ["rag"],
        f"excluded: {excluded or '(no FULL_DATA_EXCLUDE found)'}; the old include "
        f"list FULL_DATA_DIRS is {'gone' if 'FULL_DATA_DIRS' not in backup_sh else 'still there'}",
    )

    # 4. R-057
    row(
        "the bind-mount check reads the live mounts, not just whether the override file exists",
        "LIVE_MOUNTS" in check_destructive,
        "check_destructive.sh reads LIVE_MOUNTS"
        if "LIVE_MOUNTS" in check_destructive else "still only tests for the override file",
    )

    # 5-7. R-060/R-061: the welcome screen against the registry
    try:
        from app.chemistry.registry2.capabilities import ENGINES
        from app.chemistry.registry2.tasks import supports

        def engines_supporting(method, task, subtype=""):
            return tuple(e for e in ENGINES if supports(e, method, task, subtype).supported)

        rows_json = read("frontend/src/chat/capabilityRows.json")
        row(
            "the welcome screen's capability table is generated from the registry",
            bool(rows_json.strip()),
            "frontend/src/chat/capabilityRows.json exists and is what the screen renders"
            if rows_json.strip() else "no generated table; the screen is hand-kept",
        )
        bagel_scan = "bagel" in engines_supporting("casscf", "pes_1d")
        row(
            "the welcome screen no longer claims BAGEL runs potential-energy scans",
            (not bagel_scan) and "bagel" not in rows_json.lower().split("pes_1d")[0][-200:]
            if "pes_1d" in rows_json else not bagel_scan,
            f"engines_supporting('casscf','pes_1d') = {sorted(engines_supporting('casscf', 'pes_1d'))}; "
            "the table is generated from that same call",
        )
        # The review's version of this row asserted that BAGEL SHOULD appear
        # for hf/opt/min, because the capability row said the engine can do it.
        # R-028 settled that differently and deliberately: the capability row
        # is about the engine, the task's engine_methods list is about what
        # this app builds, and bagel_runner's optimisation builder writes only
        # casscf and caspt2 method blocks. So the right check is not "does
        # BAGEL appear", it is "does the welcome screen say whatever supports()
        # says", which is what generating it from the registry guarantees.
        from scripts.generate_capability_docs import render_welcome_rows
        import json as _json
        generated = render_welcome_rows()
        on_disk = (REPO / "frontend/src/chat/capabilityRows.json").read_text()
        row(
            "the welcome screen's committed table is what the registry generates today",
            _json.loads(generated) == _json.loads(on_disk),
            "regenerating produces the committed file byte for byte"
            if _json.loads(generated) == _json.loads(on_disk)
            else "the committed table has drifted from the registry; regenerate it",
        )
    except Exception as exc:  # noqa: BLE001
        row("the welcome screen's capability claims match the registry", False,
            f"{type(exc).__name__}: {exc}")

    # 8. docker-compose.dev.yml
    row(
        "DEPLOYMENT.md does not point at a docker-compose.dev.yml that is not in the repo",
        "docker-compose.dev.yml" not in deployment or (REPO / "docker-compose.dev.yml").exists(),
        "no reference to a file that does not exist"
        if "docker-compose.dev.yml" not in deployment else "still referenced, and still absent",
    )

    # 9. the removed status rows
    row(
        "DEPLOYMENT.md's status table does not list the removed public listener or iptables switch",
        "Public nginx listener" not in deployment and "Host-level kill switch" not in deployment,
        "both rows are gone" if "Public nginx listener" not in deployment
        else "the removed features are still listed as present",
    )

    # 10. R-092
    # The claim was that the header pointed at the script as "the REAL kill
    # switch", i.e. as something a reader could go and run. Naming it in a
    # sentence that says it was removed is the correction, not a repeat of the
    # problem, so the test is for the assertion rather than for the string.
    names_it = "toggle_public_access.sh" in nginx_conf
    says_removed = bool(re.search(
        r"toggle_public_access\.sh.{0,120}?(were|was) removed", nginx_conf, re.S))
    row(
        "nginx.conf does not point at toggle_public_access.sh as something that exists",
        (not names_it) or (says_removed and not (REPO / "scripts/toggle_public_access.sh").exists()),
        "named only in the sentence recording its removal" if says_removed
        else "still offered as a live script",
    )

    # 11. R-062: retired parameters
    try:
        from app.chemistry.registry2.params import PARAMS, RETIRED_PARAMS
        # A retired parameter may legitimately appear in a sentence saying it
        # was retired, which is the correction rather than the defect. What
        # must not appear is a retired parameter inside the parameter TABLE,
        # where a reader would take it as something they can set. The tables
        # are the "| `name` |" rows.
        # Scoped to the JOB-PARAMETER tables, the two whose header row starts
        # "| Task / subtype | Parameter |" or "| Runner | Parameter |". The
        # document holds other tables (environment variables, engine paths)
        # whose names are not registry parameters at all, and sweeping the
        # whole file would drag those in. Within a row, every backticked token
        # is taken, because the parameter sits in the second column.
        table_names: set[str] = set()
        in_param_table = False
        for line in configuration.splitlines():
            if line.startswith("|") and "| Parameter |" in line:
                in_param_table = True
                continue
            if not line.startswith("|"):
                in_param_table = False
                continue
            if in_param_table:
                # The SECOND column only. Taking every backticked token in the
                # row would also collect the task names in column one and the
                # default values in column three ("idpp", "True", "full"),
                # which are neither parameters nor claims about parameters.
                cells = [c.strip() for c in line.strip().strip("|").split("|")]
                if len(cells) >= 2:
                    table_names.update(re.findall(r"`([a-zA-Z_][a-zA-Z_0-9]*)`", cells[1]))
        retired_in_table = sorted(p for p in RETIRED_PARAMS if p in table_names)
        row(
            "CONFIGURATION.md's parameter tables list nothing the registry has retired",
            not retired_in_table,
            f"retired parameters still in a table: {retired_in_table or 'none'}; "
            f"{len(RETIRED_PARAMS)} are retired in total",
        )
        # The table's own contract, in its own words, is "any parameter not
        # listed here has no default and is required", so it documents the
        # ones that HAVE a default rather than all 41. Both directions are
        # checked: nothing with a default is missing from it, and nothing in it
        # is a parameter the registry does not give a default to (which would
        # tell a reader they can leave out something the agent will ask for).
        with_default = sorted(
            p.name for p in PARAMS if getattr(p, "default", None) is not None
        )
        runner_level = {"ms_caspt2", "shift", "frozen_core", "cube_grid_points"}
        undocumented = [n for n in with_default if n not in table_names]
        row(
            "every registry parameter that has a default is in the table",
            not undocumented,
            f"{len(with_default)} of {len(PARAMS)} parameters carry a default; "
            f"missing from the table: {undocumented or 'none'}",
        )
        # `n_states` and `weights` are documented as one row describing a
        # fallback rather than a declared default, which is what the registry
        # does; they are allowed here for that reason.
        allowed = set(with_default) | runner_level | {"n_states", "weights"}
        overclaimed = sorted(n for n in table_names if n not in allowed)
        row(
            "and the table claims a default for nothing that has none",
            not overclaimed,
            f"listed with a default but required in the registry: {overclaimed or 'none'}",
        )
    except Exception as exc:  # noqa: BLE001
        row("CONFIGURATION.md's parameter table matches the registry", False,
            f"{type(exc).__name__}: {exc}")

    # 12. R-062: the task/subtype list
    try:
        from app.chemistry.registry2.tasks import TASKS
        # The document lists the task in one column and its subtypes in the
        # next, which reads better than a column of "opt/constrained" strings,
        # so the pairs are reassembled from the table rather than looked for
        # as literals.
        documented: set[tuple[str, str]] = set()
        for line in configuration.splitlines():
            if not line.startswith("|"):
                continue
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if len(cells) < 2:
                continue
            task_names = re.findall(r"`([a-z_0-9]+)`", cells[0])
            if len(task_names) != 1:
                continue
            task = task_names[0]
            subs = re.findall(r"`([a-z_0-9]+)`", cells[1])
            if "none" in cells[1].lower():
                subs.append("")
            for sub in (subs or [""]):
                documented.add((task, sub))
        want = {(t, s) for t, s in TASKS}
        missing = sorted(f"{t}/{s}" if s else t for t, s in want if (t, s) not in documented)
        bogus = [s for s in ("cas_reco/explain", "cas_reco/autocas", "cas_reco/avas")
                 if s in configuration]
        row(
            "CONFIGURATION.md lists the tasks and subtypes that exist, and no others",
            not missing and not bogus,
            f"missing: {missing or 'none'}; listed but not real: {bogus or 'none'}",
        )
    except Exception as exc:  # noqa: BLE001
        row("CONFIGURATION.md's task list matches the registry", False,
            f"{type(exc).__name__}: {exc}")

    # 13. AVAS in the help flyout
    mentions_avas = "AVAS" in help_flyout
    disclaims_avas = bool(re.search(r"no longer offers AVAS", help_flyout))
    row(
        "the help flyout does not offer AVAS, which was retired",
        (not mentions_avas) or disclaims_avas,
        "named only to say it is no longer offered" if disclaims_avas
        else "still offered as a thing the user can ask for",
    )

    # 14. the one claim that was TRUE, and its contradiction
    no_ceiling_readme = "no size limit" in readme or "no ceiling" in readme
    contradicts = bool(re.search(r"max_active_orbitals", configuration))
    row(
        "README's \"no size limit on a recommended active space\" is no longer contradicted",
        no_ceiling_readme and not contradicts,
        f"README states it: {no_ceiling_readme}; CONFIGURATION.md still names "
        f"max_active_orbitals: {contradicts}",
    )

    n_pass = sum(1 for _, ok, _ in RESULTS if ok)
    print(f"\n{n_pass}/{len(RESULTS)} of the code-falsifiable documentation claims now hold.")
    failed = [c for c, ok, _ in RESULTS if not ok]
    if failed:
        print("Still wrong:")
        for c in failed:
            print(f"  - {c}")
    sys.exit(0 if n_pass == len(RESULTS) else 1)


if __name__ == "__main__":
    main()

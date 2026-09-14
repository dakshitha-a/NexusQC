"""What scripts/release_announce.sh would do to the public repository, given
what a release actually contains.

release.sh ends with one irreversible push; this script is what runs after
it, and the two failure modes that matter cannot be seen by reading it:

- After the live release HEAD *is* the new tag, so a naive "previous tag"
  lookup answers with the tag just made, the range is empty, and no issue is
  closed. The `--exclude` guards that, and only a test where HEAD is tagged
  can show it works.
- The first CHANGELOG section is longer than GitHub's 125,000-character cap
  on release notes, so the very first `gh release create` would have failed.

Runs the real functions, sourced from the script, against a scratch git
repository built here (commits carrying references to the public and to the
private repository, a closing keyword, a release tag, a fake `public`
remote) and a stubbed `gh` on PATH that records every call and answers the
few queries the script makes. Needs no stack, no network, no token: the
public repository is never touched, which is the point of testing it this
way.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from fixtures import check, summary  # noqa: E402

REPO = Path(__file__).resolve().parent.parent.parent
SCRIPT = REPO / "scripts" / "release_announce.sh"
SLUG = "dakshitha-a/NexusQC"

# The stub answers exactly what the script asks and logs every argv line to
# $GH_LOG. State files let a case say "the release already exists", "issue 5
# is a pull request", "issue 3 already carries the comment", "issue 9 is
# closed", or "commenting on #7 fails".
GH_STUB = r'''#!/usr/bin/env bash
printf '%s\n' "$*" >> "$GH_LOG"
case "$1 $2" in
  "label create") exit 0 ;;
  "release view") [ -f "$GH_STATE/release_exists" ] && exit 0 || exit 1 ;;
  "release create") touch "$GH_STATE/release_exists"; echo "https://github.com/x/y/releases/tag/$3"; exit 0 ;;
  "api repos/"*)
    path="$2"
    n="$(printf '%s' "$path" | sed -E 's#.*/issues/([0-9]+).*#\1#')"
    case "$path" in
      */comments)
        # one body per line, as --jq '.[].body' would print
        [ -f "$GH_STATE/commented_$n" ] && cat "$GH_STATE/commented_$n"
        exit 0 ;;
      *)
        # asked with --jq '.pull_request.html_url // empty' or --jq .state
        if printf '%s' "$*" | grep -q 'pull_request'; then
          [ -f "$GH_STATE/pr_$n" ] && echo "https://github.com/x/y/pull/$n"; exit 0
        fi
        [ -f "$GH_STATE/closed_$n" ] && echo closed || echo open; exit 0 ;;
    esac ;;
  "issue comment"|"pr comment")
    n="$3"; [ -f "$GH_STATE/fail_comment_$n" ] && exit 1
    # the body is the argument after --body
    body=""; while [ $# -gt 0 ]; do [ "$1" = "--body" ] && body="$2"; shift; done
    printf '%s\n' "$body" >> "$GH_STATE/commented_$n"; exit 0 ;;
  "issue edit"|"pr edit") exit 0 ;;
  "issue close"|"pr close") touch "$GH_STATE/closed_$3"; exit 0 ;;
esac
echo "gh stub: unexpected call: $*" >&2
exit 1
'''


def git(cwd: Path, *args: str) -> str:
    env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.com",
               GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@example.com")
    out = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, env=env)
    if out.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)}: {out.stderr}")
    return out.stdout.strip()


def commit(cwd: Path, message: str) -> None:
    (cwd / "f").write_text(message)
    git(cwd, "add", "f")
    git(cwd, "commit", "-q", "-m", message)


def build_repo(tmp: Path, changelog_size: int = 2000) -> Path:
    """v1.0.0 on the third commit, then four more, one of which references
    the private repository and one of which carries a closing keyword."""
    work = tmp / "work"
    work.mkdir(parents=True)
    git(work, "init", "-q", "-b", "main")
    git(work, "remote", "add", "public", f"https://github.com/{SLUG}.git")
    commit(work, "first")
    commit(work, "second\n\nRefs: dakshitha-a/NexusQC#1")   # before the tag: must not count
    commit(work, "third")
    git(work, "tag", "-a", "v1.0.0", "-m", "1.0.0")
    git(work, "tag", "-a", "bisect-marker", "-m", "not a release")
    commit(work, "fix the thing\n\nRefs: dakshitha-a/NexusQC#3")
    commit(work, "private reference\n\nRefs: dakshitha-a/NexusQC-dev#4")
    commit(work, "keyword\n\nFixes #5")
    commit(work, "two refs\n\nRefs: dakshitha-a/NexusQC#7\nRefs: dakshitha-a/NexusQC#3")
    # A CHANGELOG with an Unreleased section, the version being released, and
    # an older one, so extraction has to stop at the right heading.
    body = "- change line\n" * (changelog_size // 14)
    (work / "CHANGELOG.md").write_text(
        "# Changelog\n\n## [Unreleased]\n\n## [1.1.0] - 2026-09-14\n\n### Fixed\n\n"
        + body + "\n## [1.0.0] - 2026-08-17\n\n- old\n")
    git(work, "add", "CHANGELOG.md")
    git(work, "commit", "-q", "-m", "changelog")
    return work


def run_fn(work: Path, snippet: str) -> str:
    """Sources the script's functions and runs `snippet` in the scratch repo."""
    script = f"source {SCRIPT}\ncd {work}\n{snippet}\n"
    out = subprocess.run(["bash", "-c", script], capture_output=True, text=True)
    return out.stdout.strip()


def run_main(work: Path, tmp: Path, *args: str, state: dict[str, str] | None = None) -> tuple[int, str, list[str]]:
    """Runs the script itself with `gh` stubbed; returns exit, output, gh log."""
    bindir = tmp / "bin"
    bindir.mkdir(exist_ok=True)
    (bindir / "gh").write_text(GH_STUB)
    (bindir / "gh").chmod(0o755)
    state_dir = tmp / "state"
    # Fresh per run: each case says exactly what the public repository already
    # holds, and the previous case's answers must not leak into it.
    if state_dir.exists():
        for f in state_dir.iterdir():
            f.unlink()
    state_dir.mkdir(exist_ok=True)
    for name, content in (state or {}).items():
        (state_dir / name).write_text(content)
    log = tmp / "gh.log"
    log.write_text("")
    # issues.sh is called for ensure-labels; it also needs gh and a public
    # remote, both of which the scratch repo provides.
    (work / "scripts").mkdir(exist_ok=True)
    for name in ("release_announce.sh", "issues.sh"):
        (work / "scripts" / name).write_bytes((REPO / "scripts" / name).read_bytes())
        (work / "scripts" / name).chmod(0o755)
    env = dict(os.environ, PATH=f"{bindir}:{os.environ['PATH']}", GH_LOG=str(log), GH_STATE=str(state_dir))
    out = subprocess.run(["bash", str(work / "scripts" / "release_announce.sh"), *args],
                         cwd=work, capture_output=True, text=True, env=env)
    return out.returncode, out.stdout + out.stderr, [l for l in log.read_text().splitlines() if l]


def main() -> None:
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        work = build_repo(tmp)

        # --- the pure functions -------------------------------------------
        prev = run_fn(work, 'previous_version_tag v1.1.0')
        check("previous release tag is v1.0.0, not the bisect marker", prev == "v1.0.0", prev)

        rng = run_fn(work, 'release_range "$(previous_version_tag v1.1.0)"')
        check("range is v1.0.0..HEAD", rng == "v1.0.0..HEAD", rng)

        issues = run_fn(work, f'referenced_issues {SLUG} v1.0.0..HEAD').split()
        check("referenced issues are #3 and #7 only (not #1 before the tag, not NexusQC-dev#4, not the Fixes #5)",
              issues == ["3", "7"], str(issues))

        kw = run_fn(work, 'closing_keywords_in_range v1.0.0..HEAD')
        check("the closing keyword commit is reported", "Fixes #5" in kw, kw)

        # After the live release: HEAD is tagged with the new version.
        git(work, "tag", "-a", "v1.1.0", "-m", "1.1.0")
        prev2 = run_fn(work, 'previous_version_tag v1.1.0')
        check("with HEAD tagged v1.1.0, the previous tag is still v1.0.0 (--exclude)", prev2 == "v1.0.0", prev2)
        rng2 = run_fn(work, 'release_range "$(previous_version_tag v1.1.0)"')
        check("and the range is unchanged, so the same issues close after the tag as before it",
              rng2 == "v1.0.0..HEAD", rng2)
        git(work, "tag", "-d", "v1.1.0")

        # No release tag at all: the whole history is the release.
        git(work, "tag", "-d", "v1.0.0")
        prev0 = run_fn(work, 'previous_version_tag v1.1.0')
        rng0 = run_fn(work, 'release_range "$(previous_version_tag v1.1.0)"')
        issues0 = run_fn(work, f'referenced_issues {SLUG} "$(release_range "")"').split()
        check("first release: no previous tag, range is HEAD, and #1 is now included",
              prev0 == "" and rng0 == "HEAD" and issues0 == ["1", "3", "7"], f"{prev0!r} {rng0} {issues0}")
        git(work, "tag", "-a", "v1.0.0", "-m", "1.0.0", "HEAD~4")

        # --- release notes ------------------------------------------------
        section = run_fn(work, 'changelog_section 1.1.0')
        check("changelog section starts at its heading and stops before the next version",
              section.startswith("## [1.1.0]") and "## [1.0.0]" not in section and "- change line" in section)
        missing = run_fn(work, 'changelog_section 9.9.9')
        check("a missing section is empty, not the whole file", missing == "")

        notes_small = run_fn(work, f'release_notes 1.1.0 {SLUG} 2>/dev/null')
        check("notes under the cap are the section unchanged", notes_small.strip() == section.strip())

        big = build_repo(tmp / "big", changelog_size=140_000)
        notes_big = run_fn(big, f'release_notes 1.1.0 {SLUG} 2>/dev/null')
        size_big = run_fn(big, f'release_notes 1.1.0 {SLUG} 2>&1 >/dev/null')
        check("notes over the cap are cut below 125,000 bytes and end with the link to the tag",
              len(notes_big.encode()) < 125_000 and "blob/v1.1.0/CHANGELOG.md" in notes_big.splitlines()[-1],
              f"{len(notes_big.encode())} bytes")
        check("the reported size is the full section's, so the dry run says what was cut",
              size_big.isdigit() and int(size_big) > 125_000, size_big)
        check("the cut lands on a paragraph boundary", "\n\n---\n" in notes_big)

        # --- main, dry run ------------------------------------------------
        rc, out, log = run_main(work, tmp, "1.1.0", "--dry-run")
        check("dry run exits 0", rc == 0, out[-300:])
        check("dry run names the issues and warns about the closing keyword",
              "#3 #7" in out and "closing keywords" in out and "Fixes #5" in out)
        check("dry run makes no gh call at all", log == [], str(log))

        # --- main, live ---------------------------------------------------
        rc, out, log = run_main(work, tmp, "1.1.0", state={"pr_7": ""})
        check("live run exits 0", rc == 0, out[-400:])
        joined = "\n".join(log)
        check("labels are ensured first", log and log[0].startswith("label create"), log[:1])
        check("the release is created with --verify-tag and the notes file",
              any(l.startswith("release create v1.1.0") and "--verify-tag" in l and "--notes-file" in l for l in log))
        check("#3 (an issue): comment, remove label, close, in that order",
              [l.split()[1] for l in log if l.startswith("issue ") and " 3 " in l] == ["comment", "edit", "close"],
              str([l for l in log if " 3 " in l]))
        check("#7 (a pull request): uses the pr commands",
              [l.split()[1] for l in log if l.startswith("pr ") and " 7 " in l] == ["comment", "edit", "close"],
              str([l for l in log if " 7 " in l]))
        check("the release comment carries the tag and the release URL",
              any("comment 3" in l and "Released in v1.1.0: https://github.com/dakshitha-a/NexusQC/releases/tag/v1.1.0" in l for l in log))

        # Second run: everything already done, nothing repeated.
        rc2, out2, log2 = run_main(work, tmp, "1.1.0", state={
            "pr_7": "", "release_exists": "", "closed_3": "", "closed_7": "",
            "commented_3": "Released in v1.1.0: x", "commented_7": "Released in v1.1.0: x"})
        mutating = [l for l in log2 if l.split()[1] in ("create", "comment", "close") and not l.startswith("label ")]
        check("a second run creates, comments and closes nothing (idempotent)", rc2 == 0 and mutating == [], str(mutating))
        check("and says so", "already exists" in out2 and "already has the release comment" in out2 and "already closed" in out2)

        # One issue's comment fails: the next one is still handled, and the
        # exit code plus the re-run line survive.
        rc3, out3, log3 = run_main(work, tmp, "1.1.0", state={"pr_7": "", "fail_comment_3": ""})
        check("a failing comment on #3 does not stop #7 from being closed",
              any(l.startswith("pr close 7") for l in log3), str(log3))
        check("and the run exits non-zero with the re-run instruction",
              rc3 != 0 and "Re-run: scripts/release_announce.sh 1.1.0" in out3, out3[-200:])

        # A version that is not a version, and no remote to announce to.
        rc4, out4, _ = run_main(work, tmp, "1.1", "--dry-run")
        check("a malformed version is refused", rc4 == 2 and "MAJOR.MINOR.PATCH" in out4)

    summary()


if __name__ == "__main__":
    main()

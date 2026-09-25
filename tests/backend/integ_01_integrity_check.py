"""tests/integrity.py catches a loss, and passes when nothing was lost.

The integrity check wraps every runner, so a check that could never fail
would make every run look safe. This proves it can, without deleting
anything real: it takes one live snapshot, then compares it against edited
copies of itself, each with one kind of loss planted:

  1. the snapshot against itself: must pass, with no losses;
  2. an owned item removed: must report it by kind, id and owner;
  3. one file removed from a finished job: must name the file;
  4. an account removed: must say the account is gone;
  5. a setting changed: must be a note, not a loss.

Cases 2 and 3 need the stack to have at least one real finished job, and
are skipped with the reason if it has none.
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import integrity  # noqa: E402
from fixtures import check, skip, summary  # noqa: E402


def main() -> None:
    snap = integrity.take()
    print(f"live snapshot: {len(snap['users'])} real account(s), {len(snap['owned'])} owned item(s)")

    losses, notes = integrity.compare(snap, snap)
    check("a snapshot compared with itself reports no loss", not losses and not notes,
          f"losses={losses} notes={notes}")

    present = [k for k, v in snap["owned"].items() if v.get("present")]
    finished = [k for k, v in snap["owned"].items() if v.get("present") and v.get("files")]
    if not present:
        skip("a removed item is reported", "no real user owns anything present on this stack")
    else:
        key = present[0]
        after = copy.deepcopy(snap)
        del after["owned"][key]
        losses, _ = integrity.compare(snap, after)
        item = snap["owned"][key]
        check(f"a removed {item['kind']} is reported with its id and owner",
              any(item["id"] in line and item["owner"] in line for line in losses), str(losses))

    if not finished:
        skip("a file removed from a finished job is reported", "no real finished job on this stack")
    else:
        key = finished[0]
        fname = sorted(snap["owned"][key]["files"])[0]
        after = copy.deepcopy(snap)
        del after["owned"][key]["files"][fname]
        losses, _ = integrity.compare(snap, after)
        check(f"a file removed from finished job {snap['owned'][key]['id']} is reported by name",
              any(fname in line for line in losses), str(losses))

    if snap["users"]:
        after = copy.deepcopy(snap)
        gone = after["users"].pop(0)
        losses, _ = integrity.compare(snap, after)
        check(f"a removed account ({gone}) is reported", any(f"account {gone} is gone" in l for l in losses),
              str(losses[:3]))

    after = copy.deepcopy(snap)
    after["config"]["integ_01_probe"] = 1
    losses, notes = integrity.compare(snap, after)
    check("a changed setting is a note, not a loss", not losses and any("integ_01_probe" in n for n in notes),
          f"losses={losses} notes={notes}")

    summary()


if __name__ == "__main__":
    main()

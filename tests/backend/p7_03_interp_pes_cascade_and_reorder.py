#!/usr/bin/env python3
"""P7.2 -- interp_pes's editable-input cascade and the endpoint atom-reorder
heuristic, against real ORCA jobs (not just the pure geometry math).

Two independent pieces:

1. **Cascade template**: a hand-edited input on an interp_pes master's
   image 0 is no longer single-image-only (pes_1d's `image0_raw_input`
   behaviour, unchanged and reconfirmed here for contrast) -- it is a
   TEMPLATE applied to every image via geometry substitution
   (app/chemistry/jobs/scan_template.py), so an extra keyword/setting the
   user added survives to every image, not just the first. Verified end
   to end: a real 3-image ORCA interp_pes scan, dispatched and run to
   completion, where every child's own input.inp carries both the user's
   added keyword AND that child's own distinct geometry.

2. **Best-effort atom reorder**: two endpoints with the same elements but
   a genuinely swapped atom correspondence (not merely a different-looking
   symbols list -- see interpolate._best_atom_correspondence's own
   docstring for why a string comparison alone cannot catch this) are
   reordered rather than rejected, with a warning always attached; a
   correctly-ordered pair that has simply moved a lot is never spuriously
   relabeled; a genuine formula mismatch still hard-refuses.

Run:  PYTHONPATH=$PWD python3 tests/backend/p7_03_interp_pes_cascade_and_reorder.py
"""
from __future__ import annotations

import sys
import time

from app.agent.tools import _build_scan_images
from app.chemistry.jobs import interpolate
from app.chemistry.jobs.base import JobSpec, get_job_manager, read_spec, read_status, sub_job_ids_of
from app.chemistry.jobs.orca_runner import build_input_text
from app.chemistry.jobs.scan_template import substitute_geometry
from app.chemistry.molecule import resolve_molecule

PASS = 0
FAIL = 0


def check(label: str, ok: bool, detail: str = "") -> None:
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  [PASS] {label}")
    else:
        FAIL += 1
        print(f"  [FAIL] {label}" + (f"\n         {detail}" if detail else ""))


WATER = resolve_molecule("water").to_dict()


def _wait_terminal(sub_ids: list[str], timeout_s: float = 300) -> dict[str, str]:
    deadline = time.time() + timeout_s
    statuses: dict[str, str] = {}
    while time.time() < deadline:
        statuses = {sid: (read_status(sid) or {}).get("status") for sid in sub_ids}
        if all(s in ("completed", "failed") for s in statuses.values()):
            break
        time.sleep(1)
    return statuses


def check_reorder() -> None:
    start = WATER
    # A plausible end structure: WATER rigidly shifted a little (same
    # physical correspondence, index-for-index). end_swapped then lists
    # the two hydrogens in the OPPOSITE order -- symbols list unchanged
    # (['O','H','H'] either way), which is exactly the case a symbol-order
    # string comparison alone cannot detect (see
    # interpolate._best_atom_correspondence's own docstring).
    shift = [0.1, 0.05, 0.0]
    correct_end_coords = [[c[0] + shift[0], c[1] + shift[1], c[2] + shift[2]] for c in WATER["coords"]]
    end_swapped = {**WATER, "coords": [correct_end_coords[0], correct_end_coords[2], correct_end_coords[1]]}
    images, warnings = interpolate.build_path(start, end_swapped, 3, method="linear")
    check("swapped-H endpoint: a warning fires", len(warnings) == 1, warnings)
    check("swapped-H endpoint: 'reordered' is named in the warning", "reordered" in warnings[0], warnings)
    # image[-1] should carry end_swapped's atoms back in start's own H1/H2
    # correspondence, i.e. equal to correct_end_coords -- reordered, not
    # left in end_swapped's raw (wrong) order.
    def _close(a, b, tol=1e-6):
        return all(abs(x - y) < tol for x, y in zip(a, b))

    last = images[-1]
    check("reordered end matches the real physical correspondence, not raw list order",
          _close(last["coords"][1], correct_end_coords[1]) and _close(last["coords"][2], correct_end_coords[2]),
          last["coords"])

    # Correctly-ordered but genuinely displaced end (a real reaction path,
    # e.g. every bond stretched 40%) -- radial scaling from the shared
    # centroid keeps every atom in its own angular sector, so this is
    # unambiguously the SAME correspondence, just farther out; must NOT be
    # spuriously relabeled.
    cx = sum(c[0] for c in WATER["coords"]) / 3
    cy = sum(c[1] for c in WATER["coords"]) / 3
    cz = sum(c[2] for c in WATER["coords"]) / 3
    end_moved = {**WATER, "coords": [
        [cx + 1.4 * (c[0] - cx), cy + 1.4 * (c[1] - cy), cz + 1.4 * (c[2] - cz)] for c in WATER["coords"]
    ]}
    _images2, warnings2 = interpolate.build_path(start, end_moved, 3, method="linear")
    check("correctly-ordered-but-displaced endpoint: no spurious reorder warning",
          warnings2 == [], warnings2)

    # Different formula -- hard reject, not a reorder attempt.
    try:
        bad = {**WATER, "symbols": ["O", "H", "H", "H"], "coords": WATER["coords"] + [[9, 9, 9]]}
        interpolate.build_path(start, bad, 3)
        check("different formula: raises ValueError", False, "did not raise")
    except ValueError as e:
        check("different formula: raises ValueError", True)
        check("... naming that they cannot be a start/end pair", "cannot be a start/end pair" in str(e), str(e))


def check_substitute_geometry_errors() -> None:
    try:
        substitute_geometry("orca", "! HF STO-3G\nno geometry block here", WATER)
        check("substitute_geometry refuses a template with no geometry block", False)
    except ValueError as e:
        check("substitute_geometry refuses a template with no geometry block", True, str(e))

    try:
        substitute_geometry("bagel", "not json at all", WATER)
        check("substitute_geometry refuses invalid BAGEL JSON", False)
    except ValueError as e:
        check("substitute_geometry refuses invalid BAGEL JSON", True, str(e))


def check_cascade_e2e() -> None:
    start = WATER
    end = {**WATER, "coords": [[c[0] + 0.4, c[1], c[2]] for c in WATER["coords"]]}
    n_points = 3
    mgr = get_job_manager()

    master = JobSpec(
        task="interp_pes", subtype="", method="hf", engine="orca",
        molecule=start,
        params={"basis": "sto-3g", "n_points": n_points, "interpolation_method": "linear",
                "_scan_start_molecule": start, "_end_molecule": end},
    )
    images, coordinate_values, coordinate_label, _warnings = _build_scan_images(master.params)
    check(f"{n_points} images built", len(images) == n_points, str(len(images)))

    base_preview = build_input_text("single_point", images[0], {"method": "hf", "basis": "sto-3g"})
    template = base_preview.replace("TightSCF", "TightSCF VeryTightOpt")
    check("template substitution proven against image 0's own geometry before dispatch",
          "VeryTightOpt" in substitute_geometry("orca", template, images[0]))

    master_id = mgr.submit_scan(
        master, images, coordinate_values, coordinate_label, input_template=template,
    )
    sub_ids = sub_job_ids_of(master_id)
    check(f"{n_points} sub-jobs dispatched", len(sub_ids) == n_points, str(sub_ids))

    statuses = _wait_terminal(sub_ids)
    for sid in sub_ids:
        check(f"{sid}: reached completed", statuses.get(sid) == "completed", statuses.get(sid))

    seen_geometries = set()
    for sid in sub_ids:
        spec = read_spec(sid) or {}
        raw_input = spec.get("params", {}).get("_raw_input", "")
        check(f"{sid}: cascaded raw input carries the user's added keyword",
              "VeryTightOpt" in raw_input, raw_input[:200])
        idx = spec.get("params", {}).get("_scan_index")
        expected_o_x = images[idx]["coords"][0][0]
        check(f"{sid}: cascaded raw input carries THIS image's own geometry (O x={expected_o_x:.5f})",
              f"{expected_o_x: .8f}".strip() in raw_input.replace("  ", " "),
              raw_input)
        seen_geometries.add(raw_input.split("* xyz")[1][:80] if "* xyz" in raw_input else "")
    check("every image's cascaded input carries a DIFFERENT geometry block",
          len(seen_geometries) == n_points, seen_geometries)


def check_pes1d_unaffected() -> None:
    """Contrast case: pes_1d's image0_raw_input still applies to image 0
    only -- confirms P7.2 only changed interp_pes's behaviour."""
    start = WATER
    mgr = get_job_manager()
    master = JobSpec(
        task="pes_1d", subtype="", method="hf", engine="orca",
        molecule=start,
        params={"basis": "sto-3g", "n_points": 3,
                "coordinate": {"type": "bond", "atoms": [1, 2]}, "scan_range": [0.8, 1.3],
                "_scan_start_molecule": start},
    )
    images, coordinate_values, coordinate_label, _warnings = _build_scan_images(master.params)
    template = build_input_text("single_point", images[0], {"method": "hf", "basis": "sto-3g"})
    edited = template.replace("TightSCF", "TightSCF VeryTightOpt")
    master_id = mgr.submit_scan(
        master, images, coordinate_values, coordinate_label, image0_raw_input=edited,
    )
    sub_ids = sub_job_ids_of(master_id)
    _wait_terminal(sub_ids)
    carries_edit = []
    for sid in sub_ids:
        spec = read_spec(sid) or {}
        idx = spec.get("params", {}).get("_scan_index")
        raw_input = spec.get("params", {}).get("_raw_input")
        if raw_input and "VeryTightOpt" in raw_input:
            carries_edit.append(idx)
    check("pes_1d: only image 0 carries the hand-edited text, not every image",
          carries_edit == [0], carries_edit)


def main() -> int:
    check_reorder()
    check_substitute_geometry_errors()
    check_cascade_e2e()
    check_pes1d_unaffected()
    print(f"\n{PASS}/{PASS + FAIL} checks passed")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

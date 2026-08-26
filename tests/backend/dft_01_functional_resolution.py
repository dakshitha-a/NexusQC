"""Functional names resolve to what each engine actually calls them, and a
name that is not a whole functional is never offered.

The class this exists for fails silently, which is why it needs a test of
its own rather than a line in an existing one. Asking PySCF for `r2scan`
used to produce `MGGA_X_R2SCAN` -- r2SCAN's exchange half with no
correlation functional at all. It is a real libxc code, it parsed, it
converged, and it landed 0.32 Eh from the right answer with nothing
printed. `m062x` gave the correlation half, 9 Eh out. No engine error
means the troubleshoot flow never sees these, so nothing downstream can
catch a regression here.

Runs in-process against the resolver rather than through the API: this is
a pure function over engine name registries, and the registries (libxc's
tables, the ORCA verified list) are the thing under test.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from fixtures import check, summary  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from app.chemistry.jobs import functional as F  # noqa: E402
from app.chemistry.jobs.param_normalize import normalize_functional  # noqa: E402

# (typed by the user, engine, expected status, expected resolved name)
RESOLUTIONS = [
    # Correct names are left alone. Second-guessing a right answer is worse
    # than doing nothing.
    ("b3lyp", "pyscf", F.EXACT, "b3lyp"),
    ("r2scan", "pyscf", F.EXACT, "r2scan"),
    ("tpssh", "pyscf", F.EXACT, "tpssh"),
    ("B3LYP", "orca", F.EXACT, "B3LYP"),

    # Same request, different real name on each engine.
    ("m062x", "pyscf", F.REWRITE, "m06-2x"),
    ("m062x", "orca", F.REWRITE, "M062X"),
    ("M06-2X", "pyscf", F.REWRITE, "m06-2x"),
    # ORCA rejects the hyphenated spelling outright -- verified by running it.
    ("M06-2X", "orca", F.REWRITE, "M062X"),
    ("camb3lyp", "orca", F.REWRITE, "CAM-B3LYP"),

    # !SCAN is ORCA's relaxed-surface-scan keyword; the functional is SCANFUNC.
    ("scan", "orca", F.REWRITE, "SCANFUNC"),
    ("scan", "pyscf", F.EXACT, "scan"),

    # wB97X-D and wB97X-D3 are blacklisted in pyscf/scf/dispersion.py and no
    # install changes that; ORCA runs the D3 form natively.
    ("wb97x-d", "pyscf", F.REWRITE, "wb97x-d3bj"),
    ("wb97x-d3", "pyscf", F.REWRITE, "wb97x-d3bj"),
    # A rewrite rather than exact: ORCA spells it in caps, and matching is
    # case-insensitive while the answer is the engine's own spelling.
    ("wb97x-d3", "orca", F.REWRITE, "WB97X-D3"),
    # The unseparated spelling shares the functional but not PySCF's own
    # blacklist entry, so it used to run and silently drop the dispersion
    # term. Matched on the key now, so every spelling is refused together.
    ("wb97xd", "pyscf", F.REWRITE, "wb97x-d3bj"),

    # Dispersion is a suffix on PySCF and a separate keyword on ORCA.
    ("b3lyp-d3bj", "orca", F.REWRITE, "B3LYP D3BJ"),
    ("pbe0-d4", "pyscf", F.REWRITE, "pbe0-d4"),
]

# Names that must never be offered, and what should be offered instead.
NEVER_OFFERED = [
    ("MGGA_X_R2SCAN", "pyscf", "r2scan", "exchange half of r2SCAN"),
    ("MGGA_C_M062X", "pyscf", "m06-2x", "correlation half of M06-2X"),
    ("b88", "pyscf", None, "Becke 88 exchange, no correlation"),
    ("GGA_K_REVAPBE", "pyscf", None, "a kinetic-energy functional"),
]


def main() -> None:
    print("== each engine's own spelling ==")
    for typed, engine, want_status, want_name in RESOLUTIONS:
        r = F.resolve_functional(typed, engine)
        check(
            f"{typed!r} on {engine} -> {want_name}",
            r.status == want_status and r.resolved == want_name,
            f"got status={r.status} resolved={r.resolved!r}",
        )

    print("\n== a bare -d3 is a question, not a default ==")
    # D3(BJ) and D3(zero) are different chemistry (-75.31295765 against
    # -75.31239164 on water/STO-3G), so PySCF must ask rather than pick.
    r = F.resolve_functional("b3lyp-d3", "pyscf")
    check("b3lyp-d3 on pyscf is ambiguous, not silently resolved", r.status == F.AMBIGUOUS, str(r))
    check(
        "and it offers both damping schemes",
        set(r.options) == {"b3lyp-d3bj", "b3lyp-d3zero"},
        str(r.options),
    )
    # ORCA has meant BJ damping by a bare D3 for years, so there it resolves --
    # and since 2026-08-26 it resolves to the explicit spelling rather than
    # passing the alias through. The manual is unambiguous ("!D3 ... is thus
    # equivalent to !D3BJ"), but "B3LYP D3" on an approval card does not tell
    # the person approving it which damping they are getting, and the two are
    # different chemistry. Someone who wanted the original zero-damping form
    # had no signal they had not got it.
    r = F.resolve_functional("b3lyp-d3", "orca")
    check("b3lyp-d3 on orca resolves to the explicit B3LYP D3BJ",
          r.status == F.REWRITE and r.resolved == "B3LYP D3BJ", str(r))
    check("and the note says why, and how to ask for zero damping instead",
          "D3ZERO" in (r.note or "") and "Becke-Johnson" in (r.note or ""), str(r.note))

    # A VV10 functional carries its own non-local dispersion and ORCA rejects
    # the combination outright -- an error worth catching before a job is
    # spawned, not a preference.
    r = F.resolve_functional("wb97x-v d3", "orca")
    check("a VV10 functional refuses an added dispersion correction",
          r.status == F.AMBIGUOUS and "WB97X-V" in r.options, str(r))

    # A damping scheme is not a level of theory, however happily ORCA accepts
    # it on the simple input line.
    r = F.resolve_functional("d3bj", "orca")
    check("a bare damping keyword is not resolved as a functional",
          r.status != F.EXACT, str(r))

    print("\n== component-only names are never offered ==")
    for typed, engine, want_first, what in NEVER_OFFERED:
        r = F.resolve_functional(typed, engine)
        check(
            f"{typed} ({what}) is not accepted as given",
            r.resolved != typed,
            f"resolved={r.resolved!r}",
        )
        check(
            f"and no option offered for it is a component ({typed})",
            all(F.pyscf_accepts(o) for o in r.options) if engine == "pyscf" else True,
            str(r.options),
        )
        if want_first is not None:
            check(f"{typed} points at the real functional {want_first}", want_first in r.options, str(r.options))

    print("\n== the pools themselves ==")
    pyscf_pool = F.pyscf_functional_pool()
    check("the PySCF pool is non-trivial", len(pyscf_pool) > 200, str(len(pyscf_pool)))
    check(
        "every name in the PySCF pool is a complete, runnable functional",
        all(F.pyscf_accepts(name) for name in pyscf_pool),
        str([n for n in pyscf_pool if not F.pyscf_accepts(n)][:5]),
    )
    for missing_from_pool in ("mgga_x_r2scan", "b88", "lda_x", "gga_k_revapbe", "wb97xd"):
        check(f"{missing_from_pool} is absent from the PySCF pool", missing_from_pool not in pyscf_pool)

    orca_pool = F.orca_functional_pool()
    check("the ORCA verified pool loaded", len(orca_pool) > 100, str(len(orca_pool)))
    for real in ("B3LYP", "R2SCAN", "M062X", "WB97X-D3", "B2PLYP", "SCANFUNC"):
        check(f"{real} is in the ORCA verified pool", real in orca_pool)
    # Every one of these was rejected by a real ORCA run: table fragments,
    # %method-block component keywords, and a display name that is not a
    # keyword.
    for noise in ("X_TPSS", "C_LYP", "B97X-D3", "WHPBE0", "M06-2X", "SCAN"):
        check(f"{noise} was rejected by ORCA and is not in the pool", noise not in orca_pool)

    print("\n== normalize_functional, as the draft path calls it ==")
    value, note, options = normalize_functional("M06-2X", "orca")
    check("a rewrite changes the value", value == "M062X", repr(value))
    check("and explains itself, so the change is visible on the approval card", bool(note), repr(note))
    value, note, options = normalize_functional("b3lyp", "pyscf")
    check("a correct name is untouched and unexplained", value == "b3lyp" and note is None, f"{value!r} {note!r}")
    value, note, options = normalize_functional("b3lyp-d3", "pyscf")
    check("an ambiguous name is left alone and its options handed back",
          value == "b3lyp-d3" and len(options) == 2, f"{value!r} {options}")
    value, note, options = normalize_functional("b3lyp", None)
    check("no engine means no resolution attempt", value == "b3lyp" and note is None)

    summary()


if __name__ == "__main__":
    main()

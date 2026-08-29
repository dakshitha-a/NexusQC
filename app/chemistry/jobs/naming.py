"""Auto-generated, human-meaningful default job labels, e.g.
"H2O CASSCF(6,6)/cc-pVDZ (BAGEL)" -- used by the Job Manager whenever a
job's meta.json has no user-set label (see base.py's read_meta/write_meta);
a user rename always wins over this once one exists.
"""
from __future__ import annotations

import re
from collections import Counter
from datetime import datetime, timezone

# Keyed on (task, subtype) -- P2B.4 moved the level of theory onto
# `spec.method`, so this label no longer keys on it (a v1 job-type string
# like "tddft"/"pes_scan" never appears in `method` any more; see
# app/chemistry/jobs/dispatch.py's module docstring). The level of theory
# still shows up, via `detail` below.
#
_TASK_LABELS = {
    ("single_point", "gs"): "SP",
    ("single_point", "ee"): "SP",
    ("single_point", "grad"): "Grad",
    ("single_point", "nac"): "NAC",
    ("opt", "min"): "Opt",
    ("opt", "constrained"): "Opt",
    ("opt", "ci"): "Opt(CI)",
    ("freq", ""): "Freq",
    ("opt_freq", ""): "Opt+Freq",
    ("pes_1d", ""): "PES scan",
    # The excited-state scans share their ground-state label, the way
    # single_point/gs and single_point/ee both read "SP" above: the level of
    # theory in `detail` already says which one ran, and a name is not the
    # place to repeat it. They need entries all the same, because the lookup
    # below falls back to the raw task identifier on a miss -- without these
    # an excited-state scan would be labelled "pes_1d" in the Job Manager and
    # in every download filename built from that label.
    ("pes_1d", "ee"): "PES scan",
    ("interp_pes", ""): "Path scan",
    ("interp_pes", "ee"): "Path scan",
    ("neb_ts", ""): "NEB-TS",
    ("wigner_spectra", ""): "Wigner",
    ("cas_reco", "autocas"): "CAS reco",
    ("cas_reco", "avas"): "AVAS",
    ("blind", ""): "Custom",
    ("batch", ""): "Batch",
    ("geometry_set", ""): "Geometry set",
}


def _formula(symbols: list[str]) -> str:
    """A readable (not strictly canonical Hill-system) chemical formula:
    C first, then H, then everything else alphabetically."""
    counts = Counter(symbols)
    order = []
    if "C" in counts:
        order.append("C")
    if "H" in counts:
        order.append("H")
    order += sorted(s for s in counts if s not in ("C", "H"))
    return "".join(f"{el}{counts[el] if counts[el] > 1 else ''}" for el in order)


# Methods whose written form is not recoverable from the identifier by
# upper-casing it. `mcpdft` would come out "MCPDFT" and `lpdft` "LPDFT",
# neither of which is how the method is written anywhere in the literature.
_METHOD_LABELS = {
    "mcpdft": "MC-PDFT",
    "lpdft": "L-PDFT",
}


def _method_label(method: str) -> str:
    """A method identifier as a chemist writes it: `eom_ccsd` -> `EOM-CCSD`,
    `mcpdft` -> `MC-PDFT`.

    The v2 taxonomy stores methods as snake_case identifiers, and those are
    exactly what must never reach a name a user reads. Without the
    substitution the Job Manager listed "SPEOM_CCSD" and the matching
    download filename carried it too.
    """
    if method in _METHOD_LABELS:
        return _METHOD_LABELS[method]
    return method.upper().replace("_", "-")


def auto_job_name(spec: dict) -> str:
    molecule = spec.get("molecule") or {}
    mol_label = molecule.get("name") or _formula(molecule.get("symbols") or []) or "molecule"

    task, subtype = spec.get("task") or "", spec.get("subtype") or ""
    task_label = _TASK_LABELS.get((task, subtype), task or "job")
    method = spec.get("method") or ""
    params = spec.get("params") or {}

    detail = ""
    if method in ("casscf", "caspt2", "nevpt2", "mcpdft", "lpdft"):
        # The method name belongs here, not just the active space. Without it
        # a CASSCF and a CASPT2 on the same molecule with the same active
        # space produced byte-identical names -- and because resolve_job_label
        # is the single definition of a job's name, that one collision was
        # shared by the Job Manager, the drawer heading, the submission
        # confirmation and every download filename at once. Reported by the
        # user as "i think i saw it name them the same".
        detail = _method_label(method)
        ae, ao = params.get("active_electrons"), params.get("active_orbitals")
        if ae and ao:
            detail += f"({ae},{ao})"
    elif method == "dft" and params.get("functional"):
        # The functional is the informative part for DFT, so it stands in for
        # the method: "Opt cam-b3lyp/6-31g*" says more than "Opt DFT" would.
        detail = params["functional"]
    elif method:
        detail = _method_label(method)

    # Separated, because the two were run together into "SPHF", "Freqb3lyp"
    # and "NEB-TSb3lyp". A space also makes the whole read the way a chemist
    # writes a level of theory: "water Opt HF/sto-3g (PYSCF)".
    tail = f"{task_label} {detail}" if detail else task_label
    basis = params.get("basis")
    if basis:
        tail += f"/{basis}"

    engine = spec.get("engine", "")
    return f"{mol_label} {tail} ({engine.upper()})" if engine else f"{mol_label} {tail}"


def resolve_job_label(spec: dict | None, meta: dict | None) -> str:
    """The job's name: the user's rename if there is one, otherwise the
    auto-generated default. Factored out of server/routes/jobs.py's
    _job_row so "the job's name" has exactly one definition -- the job list,
    the drawer heading and every download filename must agree, and they
    only will if they all come through here."""
    label = (meta or {}).get("label")
    if label:
        return label
    return auto_job_name(spec) if spec else ""


def slugify_label(label: str, max_len: int = 80) -> str:
    """A job label made safe to put in a filename and in a
    Content-Disposition header.

    Case is deliberately preserved: "water_HF_sto-3g_PYSCF" reads better
    than "water_hf_sto-3g_pyscf", and the acronyms are how chemists write
    them. Everything outside [A-Za-z0-9._-] becomes an underscore, which
    covers the separators auto_job_name itself produces ("water HF/sto-3g
    (PYSCF)" -> "water_HF_sto-3g_PYSCF") and, more importantly, strips the
    quotes, newlines and semicolons that would otherwise let a
    user-supplied job label inject a header. That is a real concern, not a
    theoretical one: labels are free text set through PATCH /api/jobs/{id}
    and are interpolated straight into Content-Disposition.

    The length cap is on the slug alone, not the finished filename, so the
    date and short-id parts around it always survive.
    """
    out = []
    for ch in label or "":
        out.append(ch if (ch.isascii() and (ch.isalnum() or ch in "._-")) else "_")
    slug = re.sub(r"_+", "_", "".join(out)).strip("._-")
    return slug[:max_len].rstrip("._-")


def job_filename_stem(job_id: str, spec: dict | None, meta: dict | None, created_at: float | None) -> str:
    """`{YYYYMMDD}_{slugified label}_{short id}`, the common prefix of every
    file this job hands a user.

    Named after the job rather than its id because a downloads folder full
    of "78a32a61bab7.zip" tells you nothing about which calculation
    produced what. The short id stays on the end because labels are NOT
    unique -- the same calculation run twice produces two jobs with
    identical labels, and without a discriminator the browser silently
    appends "(1)" and you can no longer tell which file came from which
    job.

    The date is UTC, deliberately. This stem is computed independently here
    and in frontend/src/lib/jobFilename.ts, and a local-time frontend
    against a UTC backend would name the same job differently on either
    side of midnight. If either half of this changes, change both.
    """
    parts = []
    if created_at:
        try:
            parts.append(datetime.fromtimestamp(float(created_at), tz=timezone.utc).strftime("%Y%m%d"))
        except (TypeError, ValueError, OSError):
            pass  # an unparseable timestamp drops the date rather than inventing one
    slug = slugify_label(resolve_job_label(spec, meta))
    if slug:
        parts.append(slug)
    parts.append((job_id or "")[:8])
    return "_".join(p for p in parts if p) or "job"


def job_download_name(stem: str, descriptor: str, ext: str) -> str:
    """`{stem}_{descriptor}{ext}` -- the name every file a job hands a user
    is downloaded as.

    Three parts, always in this order: the safe job name (`stem`, from
    job_filename_stem above), a word saying which of the job's files this
    is (`input`, `output`, `coords`, `jobfiles`, `plot`, ...), and a real
    extension. The extension is the part that used to go missing: an
    artifact served straight off disk with no Content-Disposition header
    landed in the browser's downloads folder named after the last segment
    of its URL, so a Wigner ensemble's sampled geometries arrived as a file
    called "ensemble_xyz" that no viewer would open.

    `descriptor` is slugified for the same reason the label is: some
    descriptors are derived from a URL path segment or from a client-
    supplied filename, and neither may reach a Content-Disposition header
    intact. `ext` should carry its own leading dot, and may be empty --
    a file whose real name on disk has no suffix gets none here either,
    since inventing one is worse than omitting it.
    """
    descriptor = slugify_label(descriptor, max_len=40)
    return "_".join(p for p in (stem, descriptor) if p) + (ext or "")

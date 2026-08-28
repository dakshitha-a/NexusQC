"""Human-readable summary of a single job's current state, factored out of
app/agent/tools.py's check_job_status so the exact same text backs both the
agent's own status-check tool and the "attach jobs to a prompt" feature
(server/routes/chat.py), which needs identical wording without going
through a tool call.
"""
from __future__ import annotations

from app.chemistry.jobs import geometry_resolve, spectrum_source
from app.chemistry.jobs.base import get_job_manager, read_spec
from app.chemistry.jobs.facts import BULK_FIELDS


# A statistical ensemble is the one multi-geometry job that does NOT get
# its geometries listed. Its samples are a cloud around one equilibrium
# structure, drawn at random -- "run a new job from sample 37" is not a
# thing anyone asks, the distribution is the point, and at up to 500
# samples it is by far the largest of these. Every other task in
# BATCH_GEOMETRY_SOURCE_ARTIFACT_KEY is an ordered set someone names an
# element of: a scan or interpolated path by image number, a geometry set
# by frame, an NEB band by image (its transition state above all -- "run
# a frequency job at the TS" is the single most likely follow-up any of
# this has).
_NO_GEOMETRY_LISTING_TASKS = {"wigner_spectra"}

# How many atom lines a job's geometry section may spend in total
# (images x atoms, not images -- a 4-image path of a 90-atom molecule is
# the expensive case, not a 40-image path of water). Past this the
# endpoints are shown and the middle is described rather than printed.
# This text is the model's own input on EVERY check_job_status call, not
# only on an attach, so it has to be bounded by something.
MAX_GEOMETRY_ATOM_LINES = 400


def _format_summary_value(value: object) -> str:
    if isinstance(value, float):
        return f"{value:.6g}"
    if isinstance(value, list):
        # A list of lists is bracketed per inner list rather than flattened.
        # An excited-state scan's `state_energies_per_image` is exactly this
        # shape -- one list of per-state energies per image -- and the plain
        # recursive comma-join turned it into a single undifferentiated run
        # of numbers with no way to tell where one image ended and the next
        # began. This text IS the model's input when a job is attached to a
        # prompt, so "what are the excited-state energies along this path?"
        # was being answered from a flattened blob.
        if any(isinstance(v, list) for v in value):
            return "; ".join(
                f"[{_format_summary_value(v)}]" if isinstance(v, list)
                else _format_summary_value(v)
                for v in value
            )
        return ", ".join(_format_summary_value(v) for v in value)
    return str(value)


def _shape_descriptor(key: str, value: object) -> str:
    """What a bulk field IS, in place of what it contains.

    `orbital_table` is the field this exists for. One row per molecular
    orbital, each a full dict, is around 25,000 characters for a molecule the
    size of uracil in a double-zeta basis -- and it was rendered in full on
    every status check and every attach, for a job type that almost always has
    one. Measured over a real six-job conversation it was 250,770 of 302,315
    characters, 83% of everything the model was given, and the same job's copy
    was paid for again on each refetch.

    That was not merely wasteful. The conversation ran so far over the context
    window that the history trimmer dropped 89 of 92 messages, including the
    two job results the agent had just fetched to answer the question in front
    of it, so it answered from a hole: it reported an active space of (6e,6o)
    for a job whose spec says 12 electrons in 9 orbitals, and then explained at
    length why "a small (6e,6o) active space" behaves as it does.

    The data has not moved -- the job drawer, the MO viewer and the cube
    endpoint all still read it straight out of result.json. What changed is
    that the model is told the shape and asks `job_data` for the window it
    actually wants.
    """
    if isinstance(value, list):
        n = len(value)
        if key == "orbital_table":
            return f"{n} orbitals"
        if key == "normal_modes":
            return f"{n} modes"
        if value and isinstance(value[0], list):
            return f"{n} x {len(value[0])} values"
        return f"{n} values"
    return "present"


def _summary_as_markdown_table(summary: dict, skip: tuple = ()) -> str:
    """Renders a completed job's summary dict as a GFM table instead of a
    raw Python dict repr -- this text becomes part of the LLM's own input
    (injected as a synthetic HumanMessage when a job is attached to a
    prompt, see server/routes/chat.py's _run_turn), so giving it already-
    tabular structure here reinforces the system prompt's "prefer tables
    when presenting data" instruction rather than relying on the model to
    reformat a Python dict dump on its own."""
    if not summary:
        return "(no summary fields)"
    shown, bulk = [], []
    for k, v in summary.items():
        if k in skip:
            continue
        if k in BULK_FIELDS and v is not None:
            bulk.append(f"{k} [{_shape_descriptor(k, v)}]")
        else:
            shown.append(f"| {k} | {_format_summary_value(v)} |")
    table = "| field | value |\n|---|---|\n" + "\n".join(shown)
    if bulk:
        table += (
            "\n\nStored but not shown, because each is an unbounded array: "
            + ", ".join(bulk)
            + ". Fetch a window of one with job_data (e.g. fields=[\"orbital_table[28:32]\"], "
              "or the shortcuts \"homo\" and \"lumo\") rather than guessing at what it holds."
        )
    return table


def _spec_line(job_id: str) -> str:
    """The job's own job_type/engine/params, as one line.

    Included for COMPLETED jobs as well as failed ones. It used to appear
    only in the failed branch, which left a real gap: a completed job's
    summary dict carries none of its own input settings (no method, no
    basis, no functional -- verified against real frequency and single-point
    results on disk), and this function is the whole of what the agent can
    see about an attached job, since check_job_status returns it too. So a
    perfectly ordinary request like "run this again with a bigger basis" or
    "use the same method and basis as the attached job" was unanswerable
    from any tool the agent has, and the model's only options were to ask
    or to invent a level of theory. Inventing one is not caught by anything
    downstream -- the approval card faithfully shows whatever was picked,
    and a user who trusts their own phrasing reads it as inherited.

    Params starting with "_" stay hidden; those are internal plumbing
    (_job_dir, _raw_input, ...) that would only add noise.
    """
    spec = read_spec(job_id)
    if not spec:
        return ""
    visible_params = {k: v for k, v in spec.get("params", {}).items() if not k.startswith("_")}
    # `job_type=` here reported spec["method"] -- the level of theory, not
    # the kind of job. So a pes_1d scan read back as "job_type=dft", an opt
    # as "dft", a freq as "dft" and a cas_reco as "casscf", each of them
    # contradicting what submit_draft had printed seconds earlier. The two
    # axes have been separate since registry v2; this line had not caught up.
    task = spec.get("task") or ""
    subtype = spec.get("subtype") or ""
    task_name = f"{task}/{subtype}" if subtype else task
    return (f"Original job: task={task_name}, method={spec.get('method')}, "
            f"engine={spec.get('engine')}, params={visible_params}\n")



class _Frame:
    """Just enough of geometry_upload.GeometryFrame for _xyz_block, so a
    plain molecule dict and a parsed path frame format identically."""

    def __init__(self, name: str, symbols: list, coords: list) -> None:
        self.name, self.symbols, self.coords = name, symbols, coords


def _xyz_block(frame) -> str:
    lines = [str(len(frame.symbols)), frame.name or ""]
    for sym, (x, y, z) in zip(frame.symbols, frame.coords):
        lines.append(f"{sym:2s} {x: .8f} {y: .8f} {z: .8f}")
    return "\n".join(lines)



def _single_geometry_section(job_id: str, spec: dict) -> str:
    """The one geometry an ordinary job ran on, in the same xyz form.

    A single point, a gradient, a frequency job: `source_geometry_job_id`
    could already reuse such a geometry by id, and `geometry_parameters`
    could measure it, but neither puts the structure itself in front of
    the model -- so "is this the linear or the bent isomer?" or "shift
    that hydrogen and rerun" had nothing to read. An optimization's
    product is preferred over its input, for the same reason
    resolve_single_completed_geometry prefers it: the optimized structure
    is what the job was for.

    Bounded by the same atom-line limit as a path: a 400-atom protein
    fragment does not belong in every status check either.
    """
    molecule = ((get_job_manager().result(job_id) or {}).get("summary") or {}).get("optimized_geometry")
    optimized = bool(molecule)
    if not molecule:
        molecule = spec.get("molecule")
    symbols = (molecule or {}).get("symbols") or []
    if not symbols or len(symbols) > MAX_GEOMETRY_ATOM_LINES:
        return ""
    frame = _Frame(name=(molecule.get("name") or "geometry"), symbols=symbols,
                   coords=molecule.get("coords") or [])
    what = "optimized geometry" if optimized else "geometry this job ran on"
    return (f"\nThe {what} ({len(symbols)} atoms) -- pass this block verbatim to "
            f"set_geometry to run something new from it:\n{_xyz_block(frame)}\n")

def _ordered_geometries_section(job_id: str, spec: dict) -> str:
    """Every image's geometry on a scan/interpolated path or geometry set,
    as xyz blocks the model can hand straight back to `set_geometry`.

    The energies along a path were already here; the structures behind them
    were not, so "run an optimization from image 5" or "do a frequency job
    at the top of the barrier" had nothing to resolve against -- the model
    could see that image 5 exists and what it costs, but not what it IS.
    Written as standard xyz blocks specifically because `set_geometry`
    accepts a pasted coordinate block verbatim, so no new tool is needed to
    act on one.

    Included for a still-running master as well as a finished one. The
    geometries come from the master's own path file, written in full at
    submission time (see resolve_ordered_master_frames), so unlike the
    energies they are complete from the first moment the job exists -- and
    starting a new job from one image while the rest of the path is still
    running is a normal thing to want, not an edge case.

    Silent (empty string) for any job this does not apply to, and for a
    master whose path file cannot be read: this decorates a summary, and a
    job's results should not disappear because its geometries would not
    load.
    """
    if (spec.get("task") or "") in _NO_GEOMETRY_LISTING_TASKS:
        return ""
    frames, row_labels, coordinate_label, err = geometry_resolve.resolve_ordered_master_frames(job_id, spec)
    if err or not frames:
        # Falling through to "the one geometry this job ran on" is only
        # right for a job that HAS one. A batch master's spec.molecule is
        # geometries[0] -- a real structure, but an arbitrary one of a
        # heterogeneous set -- and a blind job's is a placeholder beside
        # raw engine text. Presenting either as "the geometry this job ran
        # on" is the exact wrong answer NO_SINGLE_GEOMETRY_TASKS exists to
        # prevent, so that same rule gates this.
        if (spec.get("task") or "") in geometry_resolve.NO_SINGLE_GEOMETRY_TASKS:
            return ""
        return _single_geometry_section(job_id, spec)
    n_atoms = len(frames[0].symbols)
    head = (
        f"\nGeometries ({len(frames)} images, {n_atoms} atoms each), numbered 1 to {len(frames)} "
        f"along {coordinate_label} = {row_labels[0]} to {row_labels[-1]}. "
        f"To run a new job from one of these, put the job id in a draft's "
        f"source_geometry_job_id and its number in source_geometry_image -- that is what "
        f"\"optimize image 5\" means. Pasting the block below into set_geometry works too, "
        f"and is the way to run on a structure you have edited rather than one of these "
        f"exactly.\n"
    )
    labelled = [
        f"\nImage {i + 1} ({coordinate_label} = {label}):\n{_xyz_block(frame)}"
        for i, (frame, label) in enumerate(zip(frames, row_labels))
    ]
    if n_atoms * len(frames) <= MAX_GEOMETRY_ATOM_LINES:
        return head + "".join(labelled) + "\n"
    # Too big to print whole. The endpoints are the two a user names most
    # often ("start from the reactant", "optimize the product"), and
    # showing them beats showing nothing; the rest is described so the
    # model says the coordinates are available rather than inventing them.
    return (
        head
        + labelled[0]
        + labelled[-1]
        + f"\n\nImages 2 to {len(frames) - 1} are not printed here ({n_atoms * len(frames)} atom lines "
          f"is past the {MAX_GEOMETRY_ATOM_LINES}-line limit for one message). Their geometries exist "
          f"and can be inspected with geometry_parameters, or downloaded from the job's path file.\n"
    )


def _spectrum_section(job_id: str, spec: dict) -> str:
    """The total spectrum an excited-state, frequency or ensemble job
    produced, as x/y a reply can quote and a plot can be built from.

    Before this, a spectrum could be looked at and not worked with: the
    curve existed as a PNG, and what reached the model was the sticks
    (excitation energies and oscillator strengths, or frequencies and IR
    intensities) or, for a pooled ensemble, nothing at all. Two methods'
    spectra could not be compared in words, let alone put on one axis.

    Described rather than printed. This used to write out 64 sampled points
    of the curve, and then told the reader in its own closing line not to
    rebuild the spectrum from them -- so it was paying for a table on every
    status check and every attach that nothing was supposed to use. What a
    reply actually quotes off a spectrum is where the band lies and where it
    peaks, so that is what this gives; the curve is one plot() or job_data
    call away. Normalized to a peak of 1, like every other view of the same
    spectrum in this app. Silent for a job with no spectrum, and silent
    (not loud) when a spectrum cannot be built: an engine that computed no
    oscillator strengths leaves a job whose OTHER results are perfectly
    good, and burying them under an error about intensities would be the
    wrong emphasis. plot(kind="spectra") says the same thing properly when
    someone actually asks for the picture.
    """
    if spectrum_source.spectrum_kind_for_job(job_id, spec) is None:
        return ""
    x, y, meta, error = spectrum_source.total_spectrum_for_job(job_id)
    if error:
        return ""
    unit = meta["axis_units"]
    fwhm = f", {meta['fwhm']:g} {unit} FWHM" if meta.get("fwhm") else ""
    peak_x = x[max(range(len(y)), key=lambda i: y[i])] if len(y) else None
    peak = f", peak at {peak_x:.4g} {unit}" if peak_x is not None else ""
    return (
        f"\nTotal spectrum ({meta['label']}{fwhm}) available over "
        f"{min(x):.4g} to {max(x):.4g} {unit}{peak}, {meta['n_points']} points, "
        f"normalized to a peak of 1.\n"
        f"The curve itself is not printed here. To draw it, or to put it on one axis "
        f"with another job's spectrum, use plot(kind=\"spectra\") with the job ids; to "
        f"quote numbers off it, ask job_data. Do not reconstruct it from memory.\n"
    )


def job_context_summary(job_id: str) -> str:
    mgr = get_job_manager()
    spec = read_spec(job_id) or {}
    geometries = _ordered_geometries_section(job_id, spec)
    spectrum = _spectrum_section(job_id, spec)
    # `optimized_geometry` renders in the generic table as a flattened dict
    # repr -- name, symbols and a run of coordinates with no structure to
    # them. The geometry section below prints the same structure as an xyz
    # block the model can act on, so keeping the table row as well would be
    # the same data twice, in the worse of the two shapes.
    skip_in_table = ("optimized_geometry",) if geometries else ()
    status = mgr.status(job_id)
    if status["status"] in ("pending", "running"):
        return f"Job {job_id} is still {status['status']} ({status.get('message', '')}).{geometries}"

    result = mgr.result(job_id)
    if result is None:
        return f"Job {job_id} finished but no result was recorded; status={status}."
    if result["status"] == "failed":
        # If the user asks for this to be troubleshooting-corrected, reuse
        # these exact job_type/engine and only change what the error
        # indicates is wrong; don't guess a different job_type from the
        # error text alone.
        return (
            f"Job {job_id} FAILED.\n{_spec_line(job_id)}"
            f"Error detail (share the relevant part with the user, don't dump all of it):\n{result['error'][:2000]}"
        )

    return (
        f"Job {job_id} completed.\n{_spec_line(job_id)}"
        f"Results:\n{_summary_as_markdown_table(result['summary'], skip=skip_in_table)}\n"
        f"{geometries}{spectrum}"
    )

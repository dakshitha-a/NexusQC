import * as Dialog from "@radix-ui/react-dialog";
import { X, Download, Atom, FileText, FileCode2, ChevronLeft, ChevronRight } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { CHILD_PAGE_SIZE, useJobChildrenQuery, useJobQuery } from "../lib/queries";
import { StatusDot, StatusLabel } from "./StatusDot";
import { KillButton } from "./KillButton";
import { UvVisPanel } from "./UvVisPanel";
import { IrSpectrumPanel } from "./IrSpectrumPanel";
import { IrSpectrumInline } from "./IrSpectrumInline";
import { MoCubeViewer } from "./MoCubeViewer";
import { OrbitalTable, pruneOrbitalRows, type OrbitalRow, type OrbitalSelection } from "./OrbitalTable";
import { VibrationTable } from "./VibrationTable";
import { FrameScrubber } from "./FrameScrubber";
import { LiveLogPanel } from "./LiveLogPanel";
import { ExcitedStateTable } from "./ExcitedStateTable";
import { VectorPerAtomTable } from "./VectorPerAtomTable";
import { UvVisSpectrumInline } from "./UvVisSpectrumInline";
import { normalizeExcitedStates, oscillatorSeries, EXCITED_STATE_SUMMARY_KEYS } from "./excitedState";
import { OptimizationEnergyPlot } from "./OptimizationEnergyPlot";
import { ModeAnimationViewer } from "./ModeAnimationViewer";
import { GeometrySetViewer } from "./GeometrySetViewer";
import { ScanFrameViewer } from "./ScanFrameViewer";
import { ScanPlot } from "./ScanPlot";
import { NebFrameViewer } from "./NebFrameViewer";
import { NebEnergyPlot } from "./NebEnergyPlot";
import { EnsembleFrameViewer } from "./EnsembleFrameViewer";
import { EnsembleSpectrumPanel } from "./EnsembleSpectrumPanel";
import { WignerBroadeningPanel } from "./WignerBroadeningPanel";
import { Flyout } from "../app-shell/Flyout";
import { DownloadButton } from "../app-shell/DownloadButton";
import { ExpandablePanel } from "../app-shell/ExpandablePanel";
import { PanelErrorBoundary } from "../app-shell/PanelErrorBoundary";
import { SearchableText, type SearchableTextHandle } from "../app-shell/SearchableText";
import { MoleculeViewer } from "../molecule/MoleculeViewer";
import { moleculeToXyzBlock } from "../molecule/xyz";
import { downloadText } from "../lib/download";
import { jobDownloadName, jobFilenameStem, rawInputFilename, rawOutputFilename } from "../lib/jobFilename";
import * as api from "../lib/api";
import type { JobRow, MoleculeDict } from "../lib/api";

/** Prev/next window controls for a master's paginated children (P7.3) --
 * shared by the scan and ensemble button lists below. Renders nothing
 * once every child fits in one page, so a typical handful-to-dozens-of-
 * images scan looks exactly as it did before pagination existed. */
function ChildPager({
  offset, total, pageSize, onOffsetChange,
}: {
  offset: number; total: number; pageSize: number; onOffsetChange: (offset: number) => void;
}) {
  if (total <= pageSize) return null;
  const start = total === 0 ? 0 : offset + 1;
  const end = Math.min(offset + pageSize, total);
  return (
    <div className="mt-1 flex items-center justify-between text-[10.5px] text-text-muted">
      <span>
        {start}-{end} of {total}
      </span>
      <div className="flex items-center gap-1">
        <button
          onClick={() => onOffsetChange(Math.max(0, offset - pageSize))}
          disabled={offset <= 0}
          className="rounded p-0.5 hover:bg-surface-raised hover:text-text disabled:opacity-25 disabled:hover:bg-transparent"
        >
          <ChevronLeft size={12} />
        </button>
        <button
          onClick={() => onOffsetChange(offset + pageSize)}
          disabled={offset + pageSize >= total}
          className="rounded p-0.5 hover:bg-surface-raised hover:text-text disabled:opacity-25 disabled:hover:bg-transparent"
        >
          <ChevronRight size={12} />
        </button>
      </div>
    </div>
  );
}

function JobGeometryFlyout({
  job, molecule, isOptimized, onClose,
}: {
  job: JobRow; molecule: MoleculeDict; isOptimized: boolean; onClose: () => void;
}) {
  const [showCoords, setShowCoords] = useState(false);
  return (
    <Flyout
      open
      onClose={onClose}
      title={molecule.name ?? "Geometry"}
      widthClassName="w-160"
      headerActions={
        <DownloadButton
          title="Download this geometry as an .xyz file"
          testId="flyout-download-geometry"
          onDownload={() =>
            downloadText(
              moleculeToXyzBlock(molecule),
              jobDownloadName(jobFilenameStem(job), isOptimized ? "optimized_coords" : "coords", ".xyz"),
              "chemical/x-xyz",
            )
          }
        />
      }
    >
      <div className="flex h-full flex-col gap-2">
        <div className="text-[11px] uppercase tracking-wide text-text-muted">
          {isOptimized ? "Optimized geometry" : "Input geometry"}
        </div>
        <ExpandablePanel>
          {(expanded) => (
            <MoleculeViewer
              molecule={molecule}
              height={expanded ? 720 : 480}
              filenameBase={jobFilenameStem(job)}
            />
          )}
        </ExpandablePanel>
        <button
          onClick={() => setShowCoords((s) => !s)}
          className="self-start text-xs text-text-muted underline decoration-dotted hover:text-text"
        >
          {showCoords ? "Hide" : "Show"} coordinates
        </button>
        {showCoords && (
          <pre className="max-h-40 overflow-y-auto rounded border border-border bg-bg p-2 font-mono text-[11px] text-text-muted">
            {moleculeToXyzBlock(molecule)}
          </pre>
        )}
      </div>
    </Flyout>
  );
}

function RawOutputFlyout({ job, onClose }: { job: JobRow; onClose: () => void }) {
  const jobId = job.job_id;
  const [text, setText] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const searchRef = useRef<SearchableTextHandle>(null);
  useEffect(() => {
    fetch(api.jobArtifactUrl(jobId, "raw_output"))
      .then((r) => (r.ok ? r.text() : Promise.reject(new Error(`HTTP ${r.status}`))))
      .then(setText)
      .catch((e) => setError(String(e)));
  }, [jobId]);
  return (
    <Flyout
      open
      onClose={onClose}
      title="Raw output"
      widthClassName="w-160"
      headerActions={
        <DownloadButton
          title="Download the raw output file"
          testId="flyout-download-raw-output"
          disabled={text == null}
          onDownload={() => {
            if (text != null) downloadText(text, rawOutputFilename(job));
          }}
        />
      }
      onEscapeKeyDown={(e) => {
        if (searchRef.current?.hasQuery()) {
          e.preventDefault();
          searchRef.current.clear();
        }
      }}
    >
      {error && <div className="text-xs text-status-failed">{error}</div>}
      {!error && text == null && <div className="text-xs text-text-muted">Loading...</div>}
      {text != null && <SearchableText ref={searchRef} text={text} />}
    </Flyout>
  );
}

function RawInputFlyout({ job, onClose }: { job: JobRow; onClose: () => void }) {
  const jobId = job.job_id;
  const [text, setText] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const searchRef = useRef<SearchableTextHandle>(null);
  useEffect(() => {
    fetch(api.jobRawInputUrl(jobId))
      .then((r) => (r.ok ? r.text() : Promise.reject(new Error(`HTTP ${r.status}`))))
      .then(setText)
      .catch((e) => setError(String(e)));
  }, [jobId]);
  return (
    <Flyout
      open
      onClose={onClose}
      title="Raw input"
      widthClassName="w-160"
      headerActions={
        <DownloadButton
          title="Download the raw input file"
          testId="flyout-download-raw-input"
          disabled={text == null}
          onDownload={() => {
            if (text != null) downloadText(text, rawInputFilename(job));
          }}
        />
      }
      onEscapeKeyDown={(e) => {
        if (searchRef.current?.hasQuery()) {
          e.preventDefault();
          searchRef.current.clear();
        }
      }}
    >
      {error && <div className="text-xs text-status-failed">{error}</div>}
      {!error && text == null && <div className="text-xs text-text-muted">Loading...</div>}
      {text != null && <SearchableText ref={searchRef} text={text} />}
    </Flyout>
  );
}

function SummaryValue({ value }: { value: unknown }) {
  if (Array.isArray(value)) {
    return <span className="font-mono">[{value.map((v) => (typeof v === "number" ? v.toFixed(4) : String(v))).join(", ")}]</span>;
  }
  if (typeof value === "number") return <span className="font-mono">{Number.isInteger(value) ? value : value.toFixed(6)}</span>;
  // Plain key/value dicts like orbitals_rendered ({"HOMO": 5, "LUMO": 6})
  // and mo_energies_eV ({"HOMO": -13.5, "LUMO": 4.7}) -- render inline
  // rather than falling through to String(value)'s "[object Object]".
  if (value && typeof value === "object") {
    return (
      <span className="font-mono">
        {Object.entries(value as Record<string, unknown>)
          .map(([k, v]) => `${k}: ${typeof v === "number" ? (Number.isInteger(v) ? v : v.toFixed(4)) : String(v)}`)
          .join(", ")}
      </span>
    );
  }
  return <span className="font-mono">{String(value)}</span>;
}

export function JobDetailDrawer({
  jobId,
  threadId,
  onClose,
}: {
  jobId: string;
  threadId?: string;
  onClose: () => void;
}) {
  const { data: job } = useJobQuery(jobId);
  const excitedStateRows = job ? normalizeExcitedStates(job) : null;
  const spectrumSeries = job ? oscillatorSeries(job) : null;
  const irFreqs = job?.summary?.["frequencies_cm-1"] as number[] | undefined;
  const irIntensities = job?.summary?.["ir_intensities_km_mol"] as (number | null)[] | undefined;
  const irSpectrumSeries =
    Array.isArray(irFreqs) && Array.isArray(irIntensities) && irIntensities.every((i) => i !== null)
      ? { frequenciesCm1: irFreqs, intensities: irIntensities as number[] }
      : null;
  const normalModes = job?.summary?.["normal_modes"] as number[][][] | undefined;
  const [selectedMode, setSelectedMode] = useState<number | null>(null);
  const orbitalTable = job?.summary?.["orbital_table"] as OrbitalRow[] | undefined;
  const [selectedOrbital, setSelectedOrbital] = useState<OrbitalSelection | null>(null);
  const [geometryOpen, setGeometryOpen] = useState(false);
  const [rawOutputOpen, setRawOutputOpen] = useState(false);
  const [rawInputOpen, setRawInputOpen] = useState(false);
  const [downloadError, setDownloadError] = useState<string | null>(null);
  const isOptimizedGeometry = Boolean(job?.summary?.["optimized_molecule"]);
  const geometryMolecule = (job?.summary?.["optimized_molecule"] as MoleculeDict | undefined) ?? job?.molecule;
  const hasRawOutput = job?.engine !== "pyscf" && Boolean(job?.artifacts?.raw_output);
  // input.inp/input.json is written unconditionally before the engine
  // runs (see get_job_raw_input's docstring) -- available as soon as the
  // job exists, unlike raw_output which only appears once complete.
  const hasRawInput = job?.engine === "orca" || job?.engine === "bagel";

  const isNebTs = job?.task === "neb_ts";
  const isActiveSpaceRec = job?.task === "cas_reco";
  const isGeometrySet = job?.task === "geometry_set";
  const isScanMaster = job?.master_kind === "scan";
  const isEnsembleMaster = job?.master_kind === "ensemble";
  const isBatchMaster = job?.master_kind === "batch";
  // One shared window (P7.3) drives both the flat child-button list and
  // whichever frame viewer is showing -- a FrameScrubber move outside the
  // loaded window re-points this at the page containing the requested
  // frame, and the button list's own Prev/Next controls move it directly.
  const [childOffset, setChildOffset] = useState(0);
  const childrenQuery = useJobChildrenQuery(
    jobId, isScanMaster || isEnsembleMaster || isBatchMaster, job?.status === "running", childOffset, CHILD_PAGE_SIZE,
  );
  const childrenPage = childrenQuery.data;
  const children = childrenPage?.items ?? [];
  const childrenTotal = childrenPage?.total ?? 0;
  const requestChildOffset = (index: number) => {
    const page = Math.max(0, Math.floor(index / CHILD_PAGE_SIZE) * CHILD_PAGE_SIZE);
    setChildOffset(page);
  };
  const [openChildJobId, setOpenChildJobId] = useState<string | null>(null);
  const [optCoordsOpen, setOptCoordsOpen] = useState(false);

  return (
    <Dialog.Root open onOpenChange={(open) => !open && onClose()}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-40 bg-black/50 data-[state=open]:animate-fade-in" />
        <Dialog.Content className="fixed right-0 top-0 z-50 flex h-full w-105 max-w-[90vw] flex-col border-l border-border bg-surface shadow-2xl data-[state=open]:animate-slide-in-right">
          {!job ? (
            <div className="p-4 text-sm text-text-muted">Loading...</div>
          ) : (
            <PanelErrorBoundary label="Job details">
              <div className="flex items-start justify-between border-b border-border px-4 py-3">
                <div className="min-w-0">
                  <Dialog.Title className="truncate text-sm font-medium text-text">
                    {job.label || job.job_id}
                  </Dialog.Title>
                  <div className="truncate font-mono text-[10.5px] text-text-muted">{job.job_id}</div>
                  <div className="mt-1 text-xs text-text-muted">
                    <StatusLabel status={job.status} />
                  </div>
                </div>
                <div className="flex items-center gap-1">
                  {/* geometry_set's own job.molecule is {} (no single
                      geometry of its own -- see JobManager.
                      submit_geometry_set), which is truthy but empty; the
                      dedicated GeometrySetViewer below already covers this
                      job's geometry, so this header shortcut is skipped
                      the same way it already is for a scan master. An
                      optimized geometry is skipped for the same reason: it
                      has its own embedded viewer in the preview pane below,
                      and a flyout over it would only repeat what is already
                      on screen. What is left for this button is the case it
                      was always for -- a job whose only geometry is the
                      input one (a single point, a gradient), which no panel
                      renders. */}
                  {geometryMolecule && !isScanMaster && !isGeometrySet && !isOptimizedGeometry && (
                    <button
                      onClick={() => setGeometryOpen(true)}
                      className="rounded p-1.5 text-text-muted hover:bg-surface-raised hover:text-text"
                      title="View geometry"
                    >
                      <Atom size={15} />
                    </button>
                  )}
                  {hasRawInput && (
                    <button
                      onClick={() => setRawInputOpen(true)}
                      className="rounded p-1.5 text-text-muted hover:bg-surface-raised hover:text-text"
                      title="View raw input"
                    >
                      <FileCode2 size={15} />
                    </button>
                  )}
                  {hasRawOutput && (
                    <button
                      onClick={() => setRawOutputOpen(true)}
                      className="rounded p-1.5 text-text-muted hover:bg-surface-raised hover:text-text"
                      title="View raw output"
                    >
                      <FileText size={15} />
                    </button>
                  )}
                  <a
                    href={api.jobDownloadUrl(job.job_id)}
                    download
                    className="rounded p-1.5 text-text-muted hover:bg-surface-raised hover:text-text"
                    title="Download job files"
                  >
                    <Download size={15} />
                  </a>
                  <KillButton job={job} threadId={threadId} />
                  <Dialog.Close className="rounded p-1.5 text-text-muted hover:bg-surface-raised hover:text-text">
                    <X size={15} />
                  </Dialog.Close>
                </div>
              </div>

              <div className="flex-1 overflow-y-auto px-4 py-3 text-sm">
                {downloadError && (
                  <div className="mb-3 flex items-start justify-between gap-2 rounded border border-status-failed/30 bg-status-failed/5 px-2 py-1.5 text-xs text-status-failed">
                    <span>Download failed: {downloadError}</span>
                    <button onClick={() => setDownloadError(null)} className="shrink-0 underline">
                      dismiss
                    </button>
                  </div>
                )}
                <div className="mb-4">
                  <div className="mb-1 text-xs font-medium uppercase tracking-wide text-text-muted">
                    {job.task}
                    {job.subtype ? `/${job.subtype}` : ""}
                    {job.method ? ` · ${job.method}` : ""}
                    {/* geometry_set (and any other master with no level of
                        theory/engine of its own) leaves both blank -- see
                        JobManager.submit_geometry_set -- so the trailing
                        middot is skipped rather than dangling before an
                        empty string. */}
                    {job.engine ? ` · ${job.engine}` : ""}
                  </div>
                  <div className="text-xs text-text-muted">{job.message}</div>
                </div>

                {job.status === "running" && (
                  <div className="mb-4">
                    <LiveLogPanel jobId={job.job_id} />
                  </div>
                )}

                <div className="mb-4">
                  <div className="mb-1.5 text-xs font-medium uppercase tracking-wide text-text-muted">Parameters</div>
                  <table className="w-full text-xs">
                    <tbody>
                      {Object.entries(job.params ?? {}).map(([k, v]) => (
                        <tr key={k} className="border-t border-border">
                          <td className="py-1 pr-3 text-text-muted">{k}</td>
                          <td className="py-1">
                            <SummaryValue value={v} />
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>

                {/* The optimized geometry, embedded rather than flown out.
                    Same shape as a scan master's Scan path panel above --
                    an ExpandablePanel wrapping the viewer, an .xyz download
                    on the heading row, and a coordinates toggle underneath
                    -- because an opt job's product IS a geometry, and the
                    thing a job's preview pane is for is showing its
                    product. Guarded exactly like the header button: a scan
                    master and a geometry set have their own frame viewers,
                    and a second geometry panel in the same drawer would be
                    two viewers competing to be the geometry. */}
                {isOptimizedGeometry && geometryMolecule && !isScanMaster && !isGeometrySet && (
                  <div className="mb-4">
                    <div className="mb-1.5 flex items-center justify-between">
                      <div className="text-xs font-medium uppercase tracking-wide text-text-muted">
                        Optimized geometry
                      </div>
                      <button
                        onClick={() =>
                          downloadText(
                            moleculeToXyzBlock(geometryMolecule),
                            jobDownloadName(jobFilenameStem(job), "optimized_coords", ".xyz"),
                            "chemical/x-xyz",
                          )
                        }
                        className="rounded p-1 text-text-muted hover:bg-surface-raised hover:text-text"
                        data-testid="drawer-download-geometry"
                        title="Download this geometry as an .xyz file"
                      >
                        <Download size={12} />
                      </button>
                    </div>
                    <ExpandablePanel>
                      {(expanded) => (
                        <MoleculeViewer
                          molecule={geometryMolecule}
                          height={expanded ? 640 : 280}
                          filenameBase={jobFilenameStem(job)}
                        />
                      )}
                    </ExpandablePanel>
                    <button
                      onClick={() => setOptCoordsOpen((c) => !c)}
                      className="mt-2 self-start text-xs text-text-muted underline decoration-dotted hover:text-text"
                    >
                      {optCoordsOpen ? "Hide" : "Show"} coordinates
                    </button>
                    {optCoordsOpen && (
                      <pre className="mt-1 max-h-40 overflow-y-auto rounded border border-border bg-bg p-2 font-mono text-[11px] text-text-muted">
                        {moleculeToXyzBlock(geometryMolecule)}
                      </pre>
                    )}
                  </div>
                )}

                {isGeometrySet && (
                  <div className="mb-4">
                    <div className="mb-1.5 text-xs font-medium uppercase tracking-wide text-text-muted">
                      {(job.summary?.["n_geometries"] as number | undefined) ?? "?"} geometries
                    </div>
                    <ExpandablePanel>
                      {(expanded) => (
                        <GeometrySetViewer job={job} threadId={threadId} height={expanded ? 640 : 280} />
                      )}
                    </ExpandablePanel>
                  </div>
                )}

                {isScanMaster && (
                  <>
                    <div className="mb-4">
                      <div className="mb-1.5 text-xs font-medium uppercase tracking-wide text-text-muted">
                        Scan path
                      </div>
                      <ExpandablePanel>
                        {(expanded) => (
                          <ScanFrameViewer
                            job={job}
                            childrenPage={childrenPage}
                            onRequestOffset={requestChildOffset}
                            height={expanded ? 640 : 280}
                          />
                        )}
                      </ExpandablePanel>
                    </div>

                    <div className="mb-4">
                      <div className="mb-1.5 text-xs font-medium uppercase tracking-wide text-text-muted">
                        {(job.summary?.["images_complete"] as number | undefined) ?? 0} of{" "}
                        {(job.summary?.["n_points"] as number | undefined) ?? childrenTotal} images complete
                        {job.summary?.["scan_job_type"] ? ` · ${job.summary["scan_job_type"]}` : ""}
                        {job.params?.["basis"] ? ` · ${job.params["basis"]}` : ""}
                      </div>
                      <div className="flex flex-col gap-1">
                        {children.map((child) => (
                          <button
                            key={child.job_id}
                            onClick={() => setOpenChildJobId(child.job_id)}
                            className="flex items-center gap-2 rounded border border-border px-2 py-1 text-left text-xs hover:bg-surface-raised"
                          >
                            <StatusDot status={child.status} />
                            <span className="min-w-0 flex-1 truncate">{child.label || child.job_id}</span>
                            <ChevronRight size={12} className="text-text-muted" />
                          </button>
                        ))}
                        {childrenTotal === 0 && (
                          <div className="text-xs text-text-muted">Sub-jobs are still being submitted...</div>
                        )}
                      </div>
                      <ChildPager
                        offset={childOffset} total={childrenTotal} pageSize={CHILD_PAGE_SIZE}
                        onOffsetChange={setChildOffset}
                      />
                    </div>

                    <div className="mb-4">
                      <div className="mb-1.5 text-xs font-medium uppercase tracking-wide text-text-muted">
                        PES plot
                      </div>
                      <ExpandablePanel>{() => <ScanPlot job={job} />}</ExpandablePanel>
                    </div>
                  </>
                )}

                {isEnsembleMaster && (
                  <>
                    <div className="mb-4">
                      <div className="mb-1.5 text-xs font-medium uppercase tracking-wide text-text-muted">
                        Sampled geometries
                      </div>
                      <ExpandablePanel>
                        {(expanded) => (
                          <EnsembleFrameViewer
                            job={job}
                            childrenPage={childrenPage}
                            onRequestOffset={requestChildOffset}
                            height={expanded ? 640 : 280}
                          />
                        )}
                      </ExpandablePanel>
                      {job.artifacts?.ensemble_xyz && (
                        <a
                          href={api.jobArtifactUrl(job.job_id, "ensemble_xyz")}
                          download
                          className="mt-1.5 flex w-fit items-center gap-1.5 text-xs text-text-muted hover:text-text"
                        >
                          <Download size={12} />
                          Download all sampled geometries (.xyz)
                        </a>
                      )}
                    </div>

                    <div className="mb-4">
                      <div className="mb-1.5 text-xs font-medium uppercase tracking-wide text-text-muted">
                        {(job.summary?.["n_dispatched"] as number | undefined) ?? 0} of{" "}
                        {(job.summary?.["n_samples"] as number | undefined) ?? childrenTotal} samples dispatched,{" "}
                        {(job.summary?.["n_complete"] as number | undefined) ?? 0} complete
                        {job.summary?.["scan_job_type"] ? ` · ${job.summary["scan_job_type"]}` : ""}
                        {job.params?.["basis"] ? ` · ${job.params["basis"]}` : ""}
                      </div>
                      {/* Up to 500 samples -- a flat one-button-per-child list (pes_scan's
                          usual handful-to-dozens shape) doesn't scale here, so this is a
                          fixed-height scrollable list instead of rendering everything flat,
                          windowed to CHILD_PAGE_SIZE at a time (P7.3) via ChildPager. */}
                      <div className="flex max-h-56 flex-col gap-1 overflow-y-auto">
                        {children.map((child) => (
                          <button
                            key={child.job_id}
                            onClick={() => setOpenChildJobId(child.job_id)}
                            className="flex items-center gap-2 rounded border border-border px-2 py-1 text-left text-xs hover:bg-surface-raised"
                          >
                            <StatusDot status={child.status} />
                            <span className="min-w-0 flex-1 truncate">{child.label || child.job_id}</span>
                            <ChevronRight size={12} className="text-text-muted" />
                          </button>
                        ))}
                        {childrenTotal === 0 && (
                          <div className="text-xs text-text-muted">Samples are still being submitted...</div>
                        )}
                      </div>
                      <ChildPager
                        offset={childOffset} total={childrenTotal} pageSize={CHILD_PAGE_SIZE}
                        onOffsetChange={setChildOffset}
                      />
                    </div>

                    {job.artifacts?.ensemble_spectrum && (
                      <div className="mb-4">
                        <div className="mb-1.5 text-xs font-medium uppercase tracking-wide text-text-muted">
                          Nuclear-ensemble spectrum
                        </div>
                        <ExpandablePanel>{() => <EnsembleSpectrumPanel jobId={job.job_id} />}</ExpandablePanel>
                      </div>
                    )}

                    <div className="mb-4">
                      <div className="mb-1.5 text-xs font-medium uppercase tracking-wide text-text-muted">
                        Live broadening
                      </div>
                      <ExpandablePanel>
                        {() => <WignerBroadeningPanel jobId={job.job_id} running={job.status === "running"} />}
                      </ExpandablePanel>
                    </div>
                  </>
                )}

                {isBatchMaster && (
                  <div className="mb-4">
                    <div className="mb-1.5 text-xs font-medium uppercase tracking-wide text-text-muted">
                      {(job.summary?.["n_complete"] as number | undefined) ?? 0} of{" "}
                      {(job.summary?.["n_children"] as number | undefined) ?? childrenTotal} jobs complete
                    </div>
                    {/* No frame viewer here, unlike scan/ensemble -- a batch's
                        children can be different tasks over different
                        geometries with no shared trajectory to scrub through.
                        Opening one recurses into its own JobDetailDrawer
                        (below), which renders whatever that child's own task
                        needs -- "the drawer already recurses" is what makes
                        this section this short. */}
                    <div className="flex max-h-72 flex-col gap-1 overflow-y-auto">
                      {children.map((child) => (
                        <button
                          key={child.job_id}
                          onClick={() => setOpenChildJobId(child.job_id)}
                          className="flex items-center gap-2 rounded border border-border px-2 py-1 text-left text-xs hover:bg-surface-raised"
                        >
                          <StatusDot status={child.status} />
                          <span className="min-w-0 flex-1 truncate">{child.label || child.job_id}</span>
                          <span className="shrink-0 text-text-muted">
                            {child.task}
                            {child.subtype ? `/${child.subtype}` : ""}
                          </span>
                          <ChevronRight size={12} className="text-text-muted" />
                        </button>
                      ))}
                      {childrenTotal === 0 && (
                        <div className="text-xs text-text-muted">Jobs are still being submitted...</div>
                      )}
                    </div>
                    <ChildPager
                      offset={childOffset} total={childrenTotal} pageSize={CHILD_PAGE_SIZE}
                      onOffsetChange={setChildOffset}
                    />
                  </div>
                )}

                {isNebTs && job && (
                  <>
                    <div className="mb-4">
                      <div className="mb-1.5 text-xs font-medium uppercase tracking-wide text-text-muted">
                        NEB-TS path
                      </div>
                      <ExpandablePanel>
                        {(expanded) => <NebFrameViewer job={job} height={expanded ? 640 : 280} />}
                      </ExpandablePanel>
                    </div>

                    <div className="mb-4">
                      <div className="mb-1.5 text-xs font-medium uppercase tracking-wide text-text-muted">
                        Reaction-path plot
                      </div>
                      <ExpandablePanel>{() => <NebEnergyPlot job={job} />}</ExpandablePanel>
                    </div>
                  </>
                )}

                {job.error && (
                  <div className="mb-4">
                    <div className="mb-1.5 text-xs font-medium uppercase tracking-wide text-status-failed">Error</div>
                    <pre className="max-h-64 overflow-y-auto whitespace-pre-wrap rounded border border-status-failed/30 bg-status-failed/5 p-2 font-mono text-[11px] text-status-failed">
                      {job.error}
                    </pre>
                  </div>
                )}

                {excitedStateRows && (
                  <div className="mb-4">
                    <div className="mb-1.5 text-xs font-medium uppercase tracking-wide text-text-muted">
                      Excited states
                    </div>
                    <ExcitedStateTable rows={excitedStateRows} method={job.method} />
                  </div>
                )}

                {job.task === "single_point" && job.subtype === "grad" &&
                  Array.isArray(job.summary?.["gradient_hartree_per_bohr"]) && (
                    <div className="mb-4">
                      <div className="mb-1.5 text-xs font-medium uppercase tracking-wide text-text-muted">
                        Gradient (Eh/Bohr)
                        {job.summary?.["target_state"] != null
                          ? ` -- state S${job.summary["target_state"]}`
                          : " -- ground state"}
                      </div>
                      <VectorPerAtomTable
                        vectors={job.summary!["gradient_hartree_per_bohr"] as number[][]}
                        symbols={job.molecule?.symbols}
                      />
                      <div className="mt-1.5 text-[11px] text-text-muted">
                        &Vert;grad&Vert; = {(job.summary!["gradient_norm_hartree_per_bohr"] as number).toFixed(6)}
                      </div>
                    </div>
                  )}

                {job.task === "single_point" && job.subtype === "nac" &&
                  Array.isArray(job.summary?.["nac_hartree_per_bohr"]) && (
                    <div className="mb-4">
                      <div className="mb-1.5 text-xs font-medium uppercase tracking-wide text-text-muted">
                        Non-adiabatic coupling (Eh/Bohr)
                        {Array.isArray(job.summary?.["state_pair"])
                          ? ` -- S${(job.summary["state_pair"] as number[])[0] - 1} / S${
                              (job.summary["state_pair"] as number[])[1] - 1
                            }`
                          : ""}
                      </div>
                      <VectorPerAtomTable
                        vectors={job.summary!["nac_hartree_per_bohr"] as number[][]}
                        symbols={job.molecule?.symbols}
                      />
                      <div className="mt-1.5 space-x-3 text-[11px] text-text-muted">
                        <span>&Vert;NAC&Vert; = {(job.summary!["nac_norm_hartree_per_bohr"] as number).toFixed(6)}</span>
                        {job.summary?.["energy_gap_eV"] != null && (
                          <span>&Delta;E = {(job.summary["energy_gap_eV"] as number).toFixed(4)} eV</span>
                        )}
                        {job.summary?.["oscillator_strength"] != null && (
                          <span>f = {(job.summary["oscillator_strength"] as number).toFixed(4)}</span>
                        )}
                      </div>
                    </div>
                  )}

                {spectrumSeries && !job.artifacts?.uvvis_spectrum && (
                  <div className="mb-4">
                    <div className="mb-1.5 flex items-center justify-between">
                      <div className="text-xs font-medium uppercase tracking-wide text-text-muted">
                        UV/Vis spectrum (auto)
                      </div>
                      <button
                        onClick={() =>
                          api.downloadPlotPng(job.job_id, "uvvis_inline").catch((e) => setDownloadError(String(e)))
                        }
                        className="rounded p-1 text-text-muted hover:bg-surface-raised hover:text-text"
                        data-testid="drawer-download-uvvis"
                        title="Download the UV/Vis spectrum as PNG"
                      >
                        <Download size={12} />
                      </button>
                    </div>
                    <ExpandablePanel>
                      {() => (
                        <UvVisSpectrumInline energiesEv={spectrumSeries.energiesEv} strengths={spectrumSeries.strengths} />
                      )}
                    </ExpandablePanel>
                  </div>
                )}

                {Array.isArray(job.summary?.["optimization_energies_hartree"]) &&
                  (job.summary["optimization_energies_hartree"] as number[]).length >= 2 && (
                    <div className="mb-4">
                      <div className="mb-1.5 flex items-center justify-between">
                        <div className="text-xs font-medium uppercase tracking-wide text-text-muted">
                          Optimization energy
                        </div>
                        <button
                          onClick={() =>
                            api
                              .downloadPlotPng(job.job_id, "optimization_energy")
                              .catch((e) => setDownloadError(String(e)))
                          }
                          className="rounded p-1 text-text-muted hover:bg-surface-raised hover:text-text"
                          data-testid="drawer-download-opt-energy"
                        title="Download the optimization energy plot as PNG"
                        >
                          <Download size={12} />
                        </button>
                      </div>
                      <ExpandablePanel>
                        {() => (
                          <OptimizationEnergyPlot energiesHartree={job.summary!["optimization_energies_hartree"] as number[]} />
                        )}
                      </ExpandablePanel>
                    </div>
                  )}

                {job.summary && Object.keys(job.summary).length > 0 && (
                  <div className="mb-4">
                    <div className="mb-1.5 text-xs font-medium uppercase tracking-wide text-text-muted">Summary</div>
                    <table className="w-full text-xs">
                      <tbody>
                        {Object.entries(job.summary)
                          .filter(
                            ([k]) =>
                              k !== "normal_modes" &&
                              k !== "frequencies_cm-1" &&
                              k !== "ir_intensities_km_mol" &&
                              k !== "optimization_energies_hartree" &&
                              // A custom job's raw_output_tail duplicates the Raw output
                              // flyout (full text, better presentation) -- only kept in
                              // the summary dict so check_job_status has something to
                              // answer questions from without a separate tool.
                              k !== "raw_output_tail" &&
                              // orbital_table is a list of {index, spin, energy_eV, occupancy}
                              // objects -- renders as "[object Object]" in this generic
                              // key/value table. Phase 4d's OrbitalTable.tsx will render it
                              // properly for mo_visualization jobs; until then, hide it here.
                              k !== "orbital_table" &&
                              // recommend_active_space fields already rendered by the dedicated
                              // "Active-space recommendation" section above (findings summary,
                              // plateau image, recommended space, dominant excitations) --
                              // duplicating them here would just be redundant, not incorrect.
                              !(
                                isActiveSpaceRec &&
                                [
                                  "literature_notes", "findings_summary", "recommended_active_electrons",
                                  "recommended_active_orbitals", "active_space_orbital_indices",
                                  "dominant_transitions",
                                ].includes(k)
                              ),
                          )
                          .filter(([k]) => !(excitedStateRows && EXCITED_STATE_SUMMARY_KEYS.has(k)))
                          .map(([k, v]) => (
                            <tr key={k} className="border-t border-border">
                              <td className="py-1 pr-3 text-text-muted">{k}</td>
                              <td className="py-1">
                                <SummaryValue value={v} />
                              </td>
                            </tr>
                          ))}
                      </tbody>
                    </table>
                  </div>
                )}

                {Array.isArray(job.summary?.["frequencies_cm-1"]) && (
                  <div className="mb-4">
                    <div className="mb-1.5 text-xs font-medium uppercase tracking-wide text-text-muted">
                      Vibrational frequencies
                    </div>
                    {/* The frequency table lives INSIDE the panel, so expanding
                        gives you the list and the animation side by side and you
                        can pick a different mode without collapsing first. When
                        the panel is `fixed inset-6` it covers everything behind
                        it, and the table used to be behind it. */}
                    <ExpandablePanel name="vibrations">
                      {(expanded) => {
                        const modeViewer = normalModes && selectedMode != null && geometryMolecule;
                        return (
                          // The tree below is deliberately the same shape in both
                          // states -- only class names and the viewer height
                          // change. Reparenting a 3Dmol viewer unmounts its
                          // container and rebuilds the WebGL context; see
                          // ExpandablePanel's own doc comment.
                          <div className={expanded ? "flex h-full min-h-0 gap-3" : "flex flex-col gap-2"}>
                            <div
                              // No right padding to clear a control cluster any
                              // more: this panel's controls are anchored in the
                              // animation viewer's own corner (see
                              // ExpandablePanel's PanelControlAnchor), not
                              // floating over whatever comes first.
                              className={
                                expanded ? "w-56 shrink-0 overflow-y-auto rounded border border-border" : ""
                              }
                            >
                              <VibrationTable
                                frequenciesCm1={job.summary!["frequencies_cm-1"] as number[]}
                                imaginaryFlags={job.summary!["imaginary_flags"] as boolean[] | undefined}
                                imaginaryThresholdCm1={
                                  job.summary!["imaginary_threshold_cm-1"] as number | undefined
                                }
                                selectedMode={selectedMode}
                                onSelectMode={normalModes ? (i) => setSelectedMode(i) : undefined}
                              />
                            </div>
                            <div className="flex min-w-0 flex-1 flex-col gap-2">
                              {/* A quick way to walk the whole series without
                                  aiming at rows. Only shown expanded -- collapsed,
                                  the table is directly above the animation. */}
                              {modeViewer && expanded && normalModes!.length > 1 && (
                                <div>
                                  <FrameScrubber
                                    index={selectedMode!}
                                    count={normalModes!.length}
                                    noun="Mode"
                                    onChange={setSelectedMode}
                                  />
                                  <div className="mt-1 text-[10.5px] text-text-muted">
                                    Mode {selectedMode! + 1} of {normalModes!.length}
                                    {irFreqs?.[selectedMode!] != null &&
                                      ` · ${irFreqs[selectedMode!].toFixed(1)} cm⁻¹`}
                                  </div>
                                </div>
                              )}
                              {modeViewer && (
                                <ModeAnimationViewer
                                  // For an opt_freq job, job.molecule is the ORIGINAL
                                  // pre-optimization geometry -- the normal modes were
                                  // computed at summary.optimized_molecule instead, so
                                  // the animation must displace atoms from THAT base
                                  // structure, not the un-optimized one. geometryMolecule
                                  // (already optimized_molecule-preferring, see above)
                                  // is the same fallback the geometry-view button uses.
                                  molecule={geometryMolecule!}
                                  displacement={normalModes![selectedMode!]}
                                  height={expanded ? 640 : 224}
                                  // 1-based mode number, matching the frequency
                                  // table the user picked it from.
                                  filename={jobDownloadName(
                                    jobFilenameStem(job),
                                    `mode${selectedMode! + 1}_${
                                      irFreqs?.[selectedMode!] != null ? Math.round(irFreqs[selectedMode!]) : "?"
                                    }cm-1`,
                                    ".png",
                                  )}
                                  onDownloadError={setDownloadError}
                                />
                              )}
                            </div>
                          </div>
                        );
                      }}
                    </ExpandablePanel>
                  </div>
                )}

                {irSpectrumSeries && !job.artifacts?.ir_spectrum && (
                  <div className="mb-4">
                    <div className="mb-1.5 flex items-center justify-between">
                      <div className="text-xs font-medium uppercase tracking-wide text-text-muted">
                        IR spectrum (auto)
                      </div>
                      <button
                        onClick={() =>
                          api.downloadPlotPng(job.job_id, "ir_spectrum_inline").catch((e) => setDownloadError(String(e)))
                        }
                        className="rounded p-1 text-text-muted hover:bg-surface-raised hover:text-text"
                        data-testid="drawer-download-ir"
                        title="Download the IR spectrum as PNG"
                      >
                        <Download size={12} />
                      </button>
                    </div>
                    <ExpandablePanel>
                      {() => (
                        <IrSpectrumInline
                          frequenciesCm1={irSpectrumSeries.frequenciesCm1}
                          intensities={irSpectrumSeries.intensities}
                        />
                      )}
                    </ExpandablePanel>
                  </div>
                )}

                {job.artifacts?.uvvis_spectrum && (
                  <div className="mb-4">
                    <div className="mb-1.5 text-xs font-medium uppercase tracking-wide text-text-muted">UV/Vis spectrum</div>
                    <ExpandablePanel>{() => <UvVisPanel jobId={job.job_id} />}</ExpandablePanel>
                  </div>
                )}

                {job.artifacts?.ir_spectrum && (
                  <div className="mb-4">
                    <div className="mb-1.5 text-xs font-medium uppercase tracking-wide text-text-muted">IR spectrum</div>
                    <ExpandablePanel>{() => <IrSpectrumPanel jobId={job.job_id} />}</ExpandablePanel>
                  </div>
                )}

                {isActiveSpaceRec && job.summary && (
                  <div className="mb-4">
                    <div className="mb-1.5 text-xs font-medium uppercase tracking-wide text-text-muted">
                      Active-space recommendation
                    </div>
                    {Boolean(job.summary["literature_notes"] || job.summary["findings_summary"]) && (
                      <div className="mb-2 rounded border border-border bg-bg p-2 text-xs text-text-muted">
                        {Boolean(job.summary["literature_notes"]) && (
                          <p className="mb-1.5">{String(job.summary["literature_notes"])}</p>
                        )}
                        {Boolean(job.summary["findings_summary"]) && <p>{String(job.summary["findings_summary"])}</p>}
                      </div>
                    )}
                    {job.artifacts?.entropy_plateau && (
                      <div className="mb-2">
                        <ExpandablePanel>
                          {() => (
                            <img
                              src={api.jobArtifactUrl(job.job_id, "entropy_plateau")}
                              alt="Single-orbital entropy plateau diagram"
                              className="w-full rounded border border-border bg-white"
                            />
                          )}
                        </ExpandablePanel>
                      </div>
                    )}
                    {job.summary["recommended_active_orbitals"] != null && (
                      <div className="mb-2 text-xs text-text">
                        <span className="font-medium">Recommended active space:</span>{" "}
                        {String(job.summary["recommended_active_electrons"])}e, {String(job.summary["recommended_active_orbitals"])}o
                        {Array.isArray(job.summary["active_space_orbital_indices"]) && (
                          <span className="text-text-muted">
                            {" "}(orbitals {(job.summary["active_space_orbital_indices"] as number[]).join(", ")})
                          </span>
                        )}
                      </div>
                    )}
                    {Array.isArray(job.summary["dominant_transitions"]) && (
                      <div className="mb-1 text-xs">
                        <span className="font-medium text-text">Dominant excitations:</span>
                        <ul className="mt-1 list-inside list-disc text-text-muted">
                          {(job.summary["dominant_transitions"] as (string | null)[]).map((t, i) => (
                            <li key={i}>State {i}: {t ?? "--"}</li>
                          ))}
                        </ul>
                      </div>
                    )}
                  </div>
                )}

                {!isNebTs &&
                  ((job.artifacts?.cubes && Object.keys(job.artifacts.cubes as object).length > 0) ||
                    (orbitalTable && orbitalTable.length > 0)) && (
                  <div className="mb-4">
                    <div className="mb-1.5 text-xs font-medium uppercase tracking-wide text-text-muted">
                      Molecular orbitals
                      {/* Cubes can be shown with no orbital_table at all (a
                          purely eagerly-rendered cube set) -- there's no
                          total to report in that case, so this only appears
                          when there actually is one. */}
                      {orbitalTable && orbitalTable.length > 0 && ` · ${orbitalTable.length} total`}
                    </div>
                    {/* Same arrangement as the vibrational-mode panel above: the
                        table is inside the panel, so expanding shows the orbital
                        list and the isosurface together and any orbital can be
                        picked straight from a row. */}
                    <ExpandablePanel name="orbitals">
                      {(expanded) => {
                        const prunedOrbitals = orbitalTable ? pruneOrbitalRows(orbitalTable).shown : [];
                        // Defaults to the HOMO, mirroring NebFrameViewer's own
                        // per-frame orbital picker -- an arbitrary index (e.g.
                        // 0, the lowest core orbital) would announce a
                        // position that doesn't match what MoCubeViewer is
                        // actually showing (its own dropdown default) until
                        // the scrubber is touched for the first time.
                        const defaultOrbitalIndex =
                          prunedOrbitals.length > 0
                            ? Math.max(...prunedOrbitals.filter((r) => r.occupancy > 0).map((r) => r.index), 1)
                            : 1;
                        const effectiveSelection =
                          selectedOrbital ?? (orbitalTable ? { index: defaultOrbitalIndex, spin: null } : null);
                        const scrubberIndex = effectiveSelection
                          ? prunedOrbitals.findIndex(
                              (r) =>
                                r.index === effectiveSelection.index &&
                                (r.spin ?? null) === (effectiveSelection.spin ?? null),
                            )
                          : -1;
                        const scrubberRow = scrubberIndex >= 0 ? prunedOrbitals[scrubberIndex] : null;
                        const hasTable = !!orbitalTable && orbitalTable.length > 0;
                        // An active-space recommendation fills in the character
                        // and localization columns, and "delocalized over C3, C6,
                        // C4, C1" wraps onto three lines in a column sized for
                        // four numeric ones. Widen only when those columns are
                        // actually populated, so an ordinary orbital list doesn't
                        // get a half-empty column beside the viewer.
                        const wideTable = orbitalTable?.some((r) => r.character || r.localized_atom);
                        return (
                          // Same shape in both states, only class names and the
                          // viewer height differ -- see the note on the
                          // vibrational panel above for why that matters.
                          <div className={expanded ? "flex h-full min-h-0 gap-3" : "flex flex-col gap-2"}>
                            <div
                              className={
                                // Empty when there is no table (a job with only
                                // eagerly-rendered cubes), so it takes no space.
                                // No right padding to clear a control cluster
                                // any more -- this panel's controls are
                                // anchored in the orbital viewer's own corner
                                // (see ExpandablePanel's PanelControlAnchor).
                                !hasTable
                                  ? ""
                                  : expanded
                                    ? `flex shrink-0 flex-col ${wideTable ? "w-96" : "w-72"}`
                                    : ""
                              }
                            >
                              {hasTable && (
                                <OrbitalTable
                                  rows={orbitalTable!}
                                  selected={selectedOrbital}
                                  onSelect={setSelectedOrbital}
                                  fill={expanded}
                                />
                              )}
                            </div>
                            <div className="flex min-w-0 flex-1 flex-col gap-2">
                              {/* A quick way to walk the whole list without
                                  aiming at rows. Only shown expanded --
                                  collapsed, the table is directly above. */}
                              {expanded && prunedOrbitals.length > 1 && scrubberRow && (
                                <div>
                                  <FrameScrubber
                                    index={scrubberIndex}
                                    count={prunedOrbitals.length}
                                    noun="Orbital"
                                    onChange={(i) => {
                                      const r = prunedOrbitals[i];
                                      setSelectedOrbital({ index: r.index, spin: r.spin });
                                    }}
                                  />
                                  <div className="mt-1 text-[10.5px] text-text-muted">
                                    Orbital {scrubberRow.index}
                                    {scrubberRow.spin ? ` (${scrubberRow.spin})` : ""} of {orbitalTable?.length} ·{" "}
                                    {scrubberRow.energy_eV?.toFixed(3)} eV
                                  </div>
                                </div>
                              )}
                              <MoCubeViewer
                                // This panel's subject is the isosurface, so
                                // its controls belong over the isosurface.
                                anchorPanelControls
                                filenameBase={jobFilenameStem(job)}
                                jobId={job.job_id}
                                cubeLabels={Object.keys((job.artifacts?.cubes as object | undefined) ?? {}).filter(
                                  (k) => !k.startsWith("idx"),
                                )}
                                orbitalSelection={selectedOrbital}
                                onClearOrbitalSelection={() => setSelectedOrbital(null)}
                                height={expanded ? 640 : 256}
                              />
                            </div>
                          </div>
                        );
                      }}
                    </ExpandablePanel>
                  </div>
                )}
              </div>
              {geometryOpen && geometryMolecule && (
                <JobGeometryFlyout
                  job={job} molecule={geometryMolecule} isOptimized={isOptimizedGeometry}
                  onClose={() => setGeometryOpen(false)}
                />
              )}
              {rawInputOpen && <RawInputFlyout job={job} onClose={() => setRawInputOpen(false)} />}
              {rawOutputOpen && <RawOutputFlyout job={job} onClose={() => setRawOutputOpen(false)} />}
              {openChildJobId && (
                <JobDetailDrawer jobId={openChildJobId} threadId={threadId} onClose={() => setOpenChildJobId(null)} />
              )}
            </PanelErrorBoundary>
          )}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

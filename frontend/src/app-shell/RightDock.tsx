import { BarChart3, Boxes, FlaskConical, ListChecks, PanelRightClose, PanelRightOpen } from "lucide-react";
import { useLayoutStore } from "../lib/layoutStore";
import { useJobsQuotaQuery } from "../lib/queries";
import { CollapsibleSection } from "./CollapsibleSection";
import { StorageUsageBadge } from "./StorageUsageBadge";
import { PanelErrorBoundary } from "./PanelErrorBoundary";
import { MoleculePanel } from "../molecule/MoleculePanel";
import { JobsPanel } from "../jobs/JobsPanel";
import { JobManagerPanel } from "../jobs/JobManagerPanel";
import { PlotsPanel } from "../plots/PlotsPanel";

export function RightDock() {
  const {
    rightDockCollapsed,
    toggleRightDock,
    moleculeCollapsed,
    toggleMolecule,
    jobsCollapsed,
    toggleJobs,
    jobManagerCollapsed,
    toggleJobManager,
    plotsCollapsed,
    togglePlots,
    rightDockWidth,
  } = useLayoutStore();
  const jobsQuotaQuery = useJobsQuotaQuery();

  if (rightDockCollapsed) {
    return (
      <div className="flex w-12 shrink-0 flex-col items-center gap-2 border-l border-border bg-surface py-2">
        <button
          onClick={toggleRightDock}
          data-testid="shell-expand-panel"
          className="rounded p-2 text-text-muted hover:bg-surface-raised hover:text-text"
          title="Expand panel"
        >
          <PanelRightOpen size={16} />
        </button>
        <div className="rounded p-2 text-text-muted" title="Molecule">
          <FlaskConical size={16} />
        </div>
        <div className="rounded p-2 text-text-muted" title="Jobs">
          <ListChecks size={16} />
        </div>
        <div className="rounded p-2 text-text-muted" title="Job manager">
          <Boxes size={16} />
        </div>
        <div className="rounded p-2 text-text-muted" title="Plots">
          <BarChart3 size={16} />
        </div>
      </div>
    );
  }

  return (
    <div className="flex min-w-0 shrink-0 flex-col border-l border-border bg-surface" style={{ width: rightDockWidth }}>
      <div className="flex items-center justify-between border-b border-border px-3 py-2">
        <span className="text-sm font-semibold">Instrument panel</span>
        <button
          onClick={toggleRightDock}
          data-testid="shell-collapse-panel"
          className="rounded p-1.5 text-text-muted hover:bg-surface-raised hover:text-text"
          title="Collapse panel"
        >
          <PanelRightClose size={15} />
        </button>
      </div>

      <div className="shrink-0 border-b border-border">
        <CollapsibleSection title="Molecule" collapsed={moleculeCollapsed} onToggle={toggleMolecule}>
          <div className="px-3 pb-3">
            <PanelErrorBoundary label="Molecule panel">
              <MoleculePanel />
            </PanelErrorBoundary>
          </div>
        </CollapsibleSection>
      </div>

      {/* Capped, not flex-1: this conversation's own job list is usually
          short (a handful of jobs), and the persistent cross-conversation
          Job Manager below is the panel the user actually wants to browse
          -- letting this one claim equal flex space left it dominating
          the dock even when nearly empty. It still scrolls internally
          (JobsPanel's own overflow-y-auto) past this cap. */}
      <div className="flex max-h-56 shrink-0 flex-col border-b border-border">
        <CollapsibleSection title="Jobs (this conversation)" collapsed={jobsCollapsed} onToggle={toggleJobs} className="min-h-0">
          <PanelErrorBoundary label="Jobs list">
            <JobsPanel />
          </PanelErrorBoundary>
        </CollapsibleSection>
      </div>

      {/* Capped for the same reason the conversation's job list is (see
          above): Job manager owns the dock's only flex-1, and a thumbnail
          gallery will happily eat every pixel it is given. Scrolls
          internally past the cap. */}
      <div className="flex max-h-64 shrink-0 flex-col border-b border-border">
        <CollapsibleSection title="Plots" collapsed={plotsCollapsed} onToggle={togglePlots} className="min-h-0">
          <PanelErrorBoundary label="Plots panel">
            <PlotsPanel />
          </PanelErrorBoundary>
        </CollapsibleSection>
      </div>

      <div className="flex min-h-0 flex-1 flex-col">
        <CollapsibleSection
          title="Job manager (all jobs)"
          collapsed={jobManagerCollapsed}
          onToggle={toggleJobManager}
          className="min-h-0 flex-1"
          headerExtra={<StorageUsageBadge quota={jobsQuotaQuery.data} label="Job artifact storage" />}
        >
          <PanelErrorBoundary label="Job manager">
            <JobManagerPanel />
          </PanelErrorBoundary>
        </CollapsibleSection>
      </div>
    </div>
  );
}

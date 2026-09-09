import { BarChart3, Boxes, FlaskConical, ListChecks, PanelRightClose, PanelRightOpen } from "lucide-react";
import { useLayoutStore } from "../lib/layoutStore";
import { useJobsQuotaQuery } from "../lib/queries";
import { CollapsibleSection } from "./CollapsibleSection";
import { StorageUsageBadge } from "./StorageUsageBadge";
import { PanelErrorBoundary } from "./PanelErrorBoundary";
import { MoleculePanel } from "../molecule/MoleculePanel";
import { JobsPanel } from "../jobs/JobsPanel";
import { JobManagerPanel } from "../jobs/JobManagerPanel";
import { JobManagerToolbar } from "../jobs/JobManagerToolbar";
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
    revealRightDockSection,
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
        {/* Buttons, not decorative divs. These were four static icons with
            tooltips, so a collapsed dock told you which panels existed and
            reached none of them: the only way in was to expand the dock by
            hand and then open the panel. The sidebar had this exact bug and
            fixed it (see LeftRail's revealSection); the dock was left behind.
            Each now expands the dock and opens its own section. */}
        {(
          [
            ["molecule", "Molecule", FlaskConical],
            ["jobs", "Jobs in this conversation", ListChecks],
            ["jobManager", "Job manager", Boxes],
            ["plots", "Plots", BarChart3],
          ] as const
        ).map(([section, label, Icon]) => (
          <button
            key={section}
            onClick={() => revealRightDockSection(section)}
            data-testid={`dock-collapsed-${section}`}
            className="rounded p-2 text-text-muted transition-colors hover:bg-surface-raised hover:text-text"
            title={`${label} (opens the panel)`}
          >
            <Icon size={16} />
          </button>
        ))}
      </div>
    );
  }

  return (
    <div
      className="flex min-w-0 shrink-0 flex-col overflow-hidden border-l border-border bg-surface"
      style={{ width: `${rightDockWidth / 16}rem` }}
    >
      <div className="flex shrink-0 items-center justify-between border-b border-border px-3 py-2">
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

      {/* The dock scrolls its own content, and this container is where that
          happens. Without it the sections below simply overflowed the dock,
          because every one of them except the Job manager is shrink-0 and the
          Molecule section has no cap at all: an open 3D viewer is ~350px, and
          ~615px once expanded, so Molecule + Jobs (max-h-56) + Plots
          (max-h-64) comes to roughly 870px of content that cannot compress.
          On any window shorter than that, the excess escaped the dock.

          What made an overflow into a visible artifact rather than a
          harmless clip is ShellLayout's row: it sets overflow-x-auto, and CSS
          computes the other axis to `auto` whenever one axis is not
          `visible`, so the row quietly became vertically scrollable too.
          Scrolling it moved the WHOLE three-panel row, dragging the sidebar
          and the chat pane up out of the viewport and leaving a black band
          along the bottom of the window. The row now pins overflow-y
          explicitly as well, so an inner overflow can never scroll the app
          again; this container is what makes that pin harmless rather than a
          clip that would hide the bottom of the dock. */}
      <div className="flex min-h-0 flex-1 flex-col overflow-y-auto">
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

        {/* min-h-36 while it is open, not min-h-0. Inside a scrolling column a
            flex-1 child with no floor is the first thing to give: it was
            squeezed to literally zero height on a short window, so the panel
            silently disappeared instead of the dock gaining a scrollbar. The
            floor is what turns "the Job manager vanished" into "the dock
            scrolls". Collapsed it keeps min-h-0, since a collapsed section
            reserving 9rem of empty space would be its own artifact. */}
        <div className={`flex flex-1 flex-col ${jobManagerCollapsed ? "min-h-0" : "min-h-36"}`}>
          <CollapsibleSection
            title="Job manager (all jobs)"
            collapsed={jobManagerCollapsed}
            onToggle={toggleJobManager}
            className="min-h-0 flex-1"
            headerExtra={
              <div className="flex shrink-0 items-center gap-1.5">
                <StorageUsageBadge quota={jobsQuotaQuery.data} label="Job artifact storage" />
                <JobManagerToolbar />
              </div>
            }
          >
            <PanelErrorBoundary label="Job manager">
              <JobManagerPanel />
            </PanelErrorBoundary>
          </CollapsibleSection>
        </div>
      </div>
    </div>
  );
}

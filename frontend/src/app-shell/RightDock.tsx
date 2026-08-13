import { FlaskConical, ListChecks, PanelRightClose, PanelRightOpen } from "lucide-react";
import { useLayoutStore } from "../lib/layoutStore";
import { CollapsibleSection } from "./CollapsibleSection";
import { MoleculePanel } from "../molecule/MoleculePanel";
import { JobsPanel } from "../jobs/JobsPanel";

export function RightDock() {
  const { rightDockCollapsed, toggleRightDock, moleculeCollapsed, toggleMolecule, jobsCollapsed, toggleJobs } =
    useLayoutStore();

  if (rightDockCollapsed) {
    return (
      <div className="flex w-12 shrink-0 flex-col items-center gap-2 border-l border-border bg-surface py-2">
        <button
          onClick={toggleRightDock}
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
      </div>
    );
  }

  return (
    <div className="flex w-105 shrink-0 flex-col border-l border-border bg-surface">
      <div className="flex items-center justify-between border-b border-border px-3 py-2">
        <span className="text-sm font-semibold">Instrument panel</span>
        <button
          onClick={toggleRightDock}
          className="rounded p-1.5 text-text-muted hover:bg-surface-raised hover:text-text"
          title="Collapse panel"
        >
          <PanelRightClose size={15} />
        </button>
      </div>

      <div className="shrink-0 border-b border-border">
        <CollapsibleSection title="Molecule" collapsed={moleculeCollapsed} onToggle={toggleMolecule}>
          <div className="px-3 pb-3">
            <MoleculePanel />
          </div>
        </CollapsibleSection>
      </div>

      <div className="flex min-h-0 flex-1 flex-col">
        <CollapsibleSection title="Jobs" collapsed={jobsCollapsed} onToggle={toggleJobs} className="min-h-0 flex-1">
          <JobsPanel />
        </CollapsibleSection>
      </div>
    </div>
  );
}

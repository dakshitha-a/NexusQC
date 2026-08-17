import { MessageSquare, BookOpen, PanelLeftClose, PanelLeftOpen, HelpCircle } from "lucide-react";
import { useLayoutStore } from "../lib/layoutStore";
import { useHelpStore } from "../lib/helpStore";
import { ConversationList } from "../chat/ConversationList";
import { KbSection } from "../kb/KbSection";
import { HelpFlyout } from "./HelpFlyout";
import { PanelErrorBoundary } from "./PanelErrorBoundary";
import { UserMenu } from "./UserMenu";

export function LeftRail() {
  const { leftRailCollapsed, toggleLeftRail, leftRailWidth } = useLayoutStore();
  // Open-state lives in a store rather than local state so the welcome screen
  // can open the same panel. It also has to be reachable from the collapsed
  // rail: leftRailCollapsed persists across reloads, so a help button that
  // only exists in the expanded branch is gone for good once someone
  // collapses the sidebar.
  const { helpOpen, openHelp, closeHelp, tutorialSeen, dismissHint } = useHelpStore();

  // Mounted unconditionally: Radix plays its exit animation on close, which a
  // conditional mount would cut off by ripping the element out immediately.
  const flyout = <HelpFlyout open={helpOpen} onClose={closeHelp} />;

  if (leftRailCollapsed) {
    return (
      <div className="flex w-12 shrink-0 flex-col items-center gap-1 border-r border-border bg-surface py-2">
        <button
          onClick={toggleLeftRail}
          className="rounded p-2 text-text-muted hover:bg-surface-raised hover:text-text"
          title="Expand sidebar"
        >
          <PanelLeftOpen size={16} />
        </button>
        <div className="mt-2 flex flex-col gap-1">
          <div className="rounded p-2 text-text-muted" title="Conversations">
            <MessageSquare size={16} />
          </div>
          <div className="rounded p-2 text-text-muted" title="Knowledge base">
            <BookOpen size={16} />
          </div>
          <button
            onClick={openHelp}
            data-testid="rail-help-collapsed"
            className="rounded p-2 text-text-muted hover:bg-surface-raised hover:text-text"
            title="How to use NexusQC"
          >
            <HelpCircle size={16} />
          </button>
          {/* Also here, not only in the expanded branch below:
              leftRailCollapsed persists across reloads, so a control that
              exists in one branch only is gone for good once someone
              collapses the sidebar. Same reason the help button is in both. */}
          <UserMenu compact />
        </div>
        {flyout}
      </div>
    );
  }

  return (
    <div className="flex min-w-0 shrink-0 flex-col border-r border-border bg-surface" style={{ width: leftRailWidth }}>
      <div className="flex items-center justify-between border-b border-border px-3 py-2">
        <span className="truncate text-sm font-semibold" title="NexusQC - Agentic Quantum Chemistry Engine">
          NexusQC
        </span>
        <div className="flex items-center gap-1">
          <button
            onClick={openHelp}
            data-testid="rail-help"
            className="relative rounded p-1.5 text-text-muted hover:bg-surface-raised hover:text-text"
            title="How to use NexusQC"
          >
            <HelpCircle size={15} />
            {!tutorialSeen && (
              <span
                aria-hidden="true"
                className="absolute right-1 top-1 size-1.5 rounded-full bg-accent"
              />
            )}
          </button>
          <UserMenu />
          <button
            onClick={toggleLeftRail}
            className="rounded p-1.5 text-text-muted hover:bg-surface-raised hover:text-text"
            title="Collapse sidebar"
          >
            <PanelLeftClose size={15} />
          </button>
        </div>
      </div>

      {/* Shown once per browser, until the tutorial is opened or this is
          dismissed. Nothing pointed at the help button before this. */}
      {!tutorialSeen && (
        <div className="flex items-start gap-2 border-b border-border bg-accent-muted/40 px-3 py-2 animate-fade-in">
          <HelpCircle size={13} className="mt-0.5 shrink-0 text-accent" />
          <div className="min-w-0 text-[11px] leading-relaxed text-text-muted">
            New here?{" "}
            <button onClick={openHelp} data-testid="first-run-hint-open" className="text-accent hover:underline">
              Read the two-minute tutorial
            </button>{" "}
            to see what NexusQC can do.
          </div>
          <button
            onClick={dismissHint}
            data-testid="first-run-hint-dismiss"
            className="shrink-0 text-text-muted hover:text-text"
            title="Dismiss"
          >
            &times;
          </button>
        </div>
      )}

      <div className="flex min-h-0 flex-1 flex-col overflow-y-auto">
        <PanelErrorBoundary label="Conversations">
          <ConversationList />
        </PanelErrorBoundary>
        <div className="border-t border-border">
          <PanelErrorBoundary label="Knowledge base">
            <KbSection />
          </PanelErrorBoundary>
        </div>
      </div>
      {flyout}
    </div>
  );
}

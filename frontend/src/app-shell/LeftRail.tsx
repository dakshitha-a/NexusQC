import { MessageSquare, BookOpen, FileText, Archive, Inbox, PanelLeftClose, PanelLeftOpen, HelpCircle } from "lucide-react";
import { useLayoutStore } from "../lib/layoutStore";
import { useHelpStore } from "../lib/helpStore";
import { ConversationList } from "../chat/ConversationList";
import { KbSection } from "../kb/KbSection";
import { FilesSection } from "../files/FilesSection";
import { ProjectsSection } from "../projects/ProjectsSection";
import { SharedWithMeSection } from "../sharing/SharedWithMeSection";
import { useAuth } from "../auth/AuthContext";
import { HelpFlyout } from "./HelpFlyout";
import { PanelErrorBoundary } from "./PanelErrorBoundary";
import { UserMenu } from "./UserMenu";

export function LeftRail() {
  const { leftRailCollapsed, toggleLeftRail, leftRailWidth, revealLeftRailSection } = useLayoutStore();
  const { user } = useAuth();

  // Expands the rail, opens the named section, and scrolls it into view.
  // The scroll is imperative because the sections are four independent
  // components with no shared scroll controller, and doing it on the next
  // frame is what makes it land: the rail has only just re-rendered from
  // its 48px icon strip to its full width, so the element does not exist
  // at its final position yet when this runs.
  const revealSection = (section: Parameters<typeof revealLeftRailSection>[0]) => {
    revealLeftRailSection(section);
    requestAnimationFrame(() => {
      const target =
        section === "conversations"
          ? document.querySelector("[data-testid='conversation-list']")
          : document.querySelector(`[data-testid='section-${section === "kb" ? "knowledge-base" : section}-toggle']`);
      target?.scrollIntoView({ block: "nearest" });
    });
  };
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
        {/* Buttons, not decorative divs. These were four static icons with
            tooltips, so a collapsed rail told you which sections existed and
            reached none of them: the only way in was to expand the rail by
            hand and then open the section, two gestures to do one thing.
            Each now expands the rail, opens its own section and scrolls to
            it. (Files had no icon here at all until the Projects work added
            both, which is how the whole gap was noticed: a section that
            exists only in the expanded branch is invisible to anyone who has
            ever collapsed the rail, and leftRailCollapsed persists across
            reloads.) */}
        <div className="mt-2 flex flex-col gap-1">
          {([
            ["conversations", "Conversations", MessageSquare],
            ["kb", "Knowledge base", BookOpen],
            ["files", "Files", FileText],
            ["projects", "Projects", Archive],
            // Only listed when auth is configured: the sharing routes are
            // not mounted without it, so on a single-user deployment this
            // icon would open a section with nothing behind it. Kept in the
            // collapsed strip rather than only in the expanded rail because
            // leftRailCollapsed persists across reloads, so the collapsed
            // strip is the state a returning user actually lands in --
            // proj_03 caught Files missing here for exactly that reason.
            ...(user ? [["shares", "Shared with me", Inbox] as const] : []),
          ] as const).map(([section, label, Icon]) => (
            <button
              key={section}
              onClick={() => revealSection(section)}
              data-testid={`rail-collapsed-${section}`}
              className="rounded p-2 text-text-muted hover:bg-surface-raised hover:text-text"
              title={`${label} (opens the sidebar)`}
            >
              <Icon size={16} />
            </button>
          ))}
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
    <div className="flex min-w-0 shrink-0 flex-col border-r border-border bg-surface" style={{ width: `${leftRailWidth / 16}rem` }}>
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
          <div className="min-w-0 text-2xs leading-relaxed text-text-muted">
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
        <div className="border-t border-border">
          <PanelErrorBoundary label="Files">
            <FilesSection />
          </PanelErrorBoundary>
        </div>
        <div className="border-t border-border">
          <PanelErrorBoundary label="Projects">
            <ProjectsSection />
          </PanelErrorBoundary>
        </div>
        {user && (
          <div className="border-t border-border">
            <PanelErrorBoundary label="Shared with me">
              <SharedWithMeSection />
            </PanelErrorBoundary>
          </div>
        )}
      </div>
      {flyout}
    </div>
  );
}

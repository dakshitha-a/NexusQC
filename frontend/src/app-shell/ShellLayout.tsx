import { LeftRail } from "./LeftRail";
import { RightDock } from "./RightDock";
import { PanelErrorBoundary } from "./PanelErrorBoundary";
import { ChatPane } from "../chat/ChatPane";

// The fixed-viewport app shell: html/body/#root are height:100dvh with
// overflow:hidden (see index.css) so the PAGE itself never scrolls -- only
// the three regions below (chat's message list, and the right dock's
// molecule/jobs panels) scroll independently. This is the actual fix for
// the "scroll all the way up/down to see X" complaint the rewrite was
// asked to solve, not a cosmetic choice.
//
// LeftRail/ChatPane/RightDock are each wrapped in their own
// PanelErrorBoundary (LeftRail's own KB section, RightDock's job panels,
// and JobDetailDrawer get further nested boundaries of their own) so a
// render crash in one region doesn't blank the whole app -- see
// PanelErrorBoundary's own comment for why this didn't exist before.
export function ShellLayout() {
  return (
    <div className="flex h-full w-full">
      <PanelErrorBoundary label="Sidebar">
        <LeftRail />
      </PanelErrorBoundary>
      <PanelErrorBoundary label="Chat">
        <ChatPane />
      </PanelErrorBoundary>
      <PanelErrorBoundary label="Instrument panel">
        <RightDock />
      </PanelErrorBoundary>
    </div>
  );
}

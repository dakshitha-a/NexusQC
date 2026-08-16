import { useState } from "react";
import { ShieldCheck, LogOut } from "lucide-react";
import { LeftRail } from "./LeftRail";
import { RightDock } from "./RightDock";
import { PanelErrorBoundary } from "./PanelErrorBoundary";
import { ChatPane } from "../chat/ChatPane";
import { ResizeHandle } from "./ResizeHandle";
import { AdminPanel } from "../admin/AdminPanel";
import { useAuth } from "../auth/AuthContext";
import {
  useLayoutStore,
  LEFT_RAIL_MIN,
  LEFT_RAIL_MAX,
  RIGHT_DOCK_MIN,
  RIGHT_DOCK_MAX,
} from "../lib/layoutStore";

// The account/admin affordance in the corner -- deliberately local
// component state (not layoutStore) for whether the admin panel is open,
// since there's no reason for that to persist across a reload the way
// panel widths/collapse state do. Renders nothing at all when auth isn't
// configured for this deployment (user is null, see AuthContext.tsx),
// preserving today's local-dev look with zero chrome added.
function AccountBar() {
  const { user, logout } = useAuth();
  const [adminOpen, setAdminOpen] = useState(false);
  if (!user) return null;
  return (
    <>
      <div className="pointer-events-none absolute right-2 top-2 z-30 flex items-center gap-1.5">
        <span className="pointer-events-none rounded bg-surface/80 px-2 py-1 text-[11px] text-text-muted backdrop-blur-sm">
          {user.username}
        </span>
        {user.role === "admin" && (
          <button
            onClick={() => setAdminOpen(true)}
            className="pointer-events-auto flex items-center gap-1 rounded bg-surface/80 px-2 py-1 text-[11px] text-text-muted backdrop-blur-sm hover:bg-surface-raised hover:text-text"
            title="Admin console"
          >
            <ShieldCheck size={12} /> Admin
          </button>
        )}
        <button
          onClick={logout}
          className="pointer-events-auto flex items-center gap-1 rounded bg-surface/80 px-2 py-1 text-[11px] text-text-muted backdrop-blur-sm hover:bg-surface-raised hover:text-text"
          title="Log out"
        >
          <LogOut size={12} /> Log out
        </button>
      </div>
      {adminOpen && <AdminPanel onClose={() => setAdminOpen(false)} />}
    </>
  );
}

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
//
// LeftRail/RightDock are drag-resizable (ResizeHandle, widths in
// layoutStore) and ChatPane -- the only flex-1 region -- carries min-w-0
// so it can actually shrink below its content's intrinsic width instead of
// pushing RightDock off the right edge. That combination was missing
// before: a wide, unwrapped assistant message (e.g. a many-column markdown
// table) forced ChatPane past its share of the row, and since this
// container had no overflow-x handling, RightDock was shoved fully out of
// the viewport with no way to scroll to it. overflow-x-auto here is a
// safety net for the remaining edge case -- LeftRail/RightDock dragged
// wide on a since-shrunk browser window -- not the primary fix; the
// primary fix is min-w-0 plus AssistantBubble's table/pre overflow
// handling (see MessageBubble.tsx) so wide content scrolls inside its own
// bubble instead of ever forcing the row wider in the first place.
export function ShellLayout() {
  const {
    leftRailCollapsed,
    rightDockCollapsed,
    leftRailWidth,
    rightDockWidth,
    setLeftRailWidth,
    setRightDockWidth,
  } = useLayoutStore();

  return (
    <div className="relative flex h-full w-full overflow-x-auto">
      <PanelErrorBoundary label="Account">
        <AccountBar />
      </PanelErrorBoundary>
      <PanelErrorBoundary label="Sidebar">
        <LeftRail />
      </PanelErrorBoundary>
      {!leftRailCollapsed && (
        <ResizeHandle
          width={leftRailWidth}
          onResize={setLeftRailWidth}
          min={LEFT_RAIL_MIN}
          max={LEFT_RAIL_MAX}
          direction={1}
          label="sidebar"
        />
      )}
      <PanelErrorBoundary label="Chat">
        <ChatPane />
      </PanelErrorBoundary>
      {!rightDockCollapsed && (
        <ResizeHandle
          width={rightDockWidth}
          onResize={setRightDockWidth}
          min={RIGHT_DOCK_MIN}
          max={RIGHT_DOCK_MAX}
          direction={-1}
          label="instrument panel"
        />
      )}
      <PanelErrorBoundary label="Instrument panel">
        <RightDock />
      </PanelErrorBoundary>
    </div>
  );
}

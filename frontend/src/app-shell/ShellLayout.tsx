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

// The account/admin affordance -- deliberately local component state (not
// layoutStore) for whether the admin panel is open, since there's no
// reason for that to persist across a reload the way panel widths/collapse
// state do. Renders nothing at all when auth isn't configured for this
// deployment (user is null, see AuthContext.tsx), preserving today's
// local-dev look with zero chrome added.
//
// F-013 fix: this used to be an absolutely-positioned overlay
// (`pointer-events-none absolute right-2 top-2 z-30`) floating over the
// top-right corner of the shell. That corner is exactly where RightDock
// puts its own controls in BOTH of its states -- "Collapse panel" in the
// expanded header, "Expand panel" at the top of the collapsed 48px rail --
// so the overlay sat on top of them at every viewport from 1280 to 2560,
// and a click aimed at the collapse toggle landed on "Log out" instead: a
// destructive misclick on a control the user believes is a layout toggle.
//
// It is now a real row in the shell's own flow instead. Reserving
// horizontal space inside the dock header was considered first and
// rejected: it cannot work for the collapsed rail, which is only 48px wide
// and could never reserve this bar's ~200px, so it would have needed a
// per-dock-state special case to stay correct. Flow layout guarantees no
// overlap in every state, at every width, with no z-index arms race and
// nothing to keep in sync. The bar renders only when there is a user, so a
// no-auth deployment gets no strip and loses no vertical space.
function AccountBar() {
  const { user, logout } = useAuth();
  const [adminOpen, setAdminOpen] = useState(false);
  if (!user) return null;
  return (
    <>
      <div
        data-testid="shell-account-bar"
        className="flex shrink-0 items-center justify-end gap-1.5 border-b border-border bg-surface px-2 py-1"
      >
        <span className="rounded px-2 py-1 text-[11px] text-text-muted">{user.username}</span>
        {user.role === "admin" && (
          <button
            onClick={() => setAdminOpen(true)}
            data-testid="admin-open"
            className="flex items-center gap-1 rounded px-2 py-1 text-[11px] text-text-muted hover:bg-surface-raised hover:text-text"
            title="Admin console"
          >
            <ShieldCheck size={12} /> Admin
          </button>
        )}
        <button
          onClick={logout}
          data-testid="shell-logout"
          className="flex items-center gap-1 rounded px-2 py-1 text-[11px] text-text-muted hover:bg-surface-raised hover:text-text"
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

  // Column: the account bar (when auth is configured) is a real row above
  // the three panels rather than an overlay on top of them -- see
  // AccountBar's own comment for why (F-013). The inner row keeps `relative`
  // because ChatPane's "jump to latest" pill positions against it, and
  // min-h-0 so the panels' own scroll containers still bound correctly
  // instead of growing the row past the viewport.
  return (
    <div className="flex h-full w-full flex-col">
      <PanelErrorBoundary label="Account">
        <AccountBar />
      </PanelErrorBoundary>
      <div className="relative flex min-h-0 w-full flex-1 overflow-x-auto">
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
    </div>
  );
}

import { LeftRail } from "./LeftRail";
import { RightDock } from "./RightDock";
import { PanelErrorBoundary } from "./PanelErrorBoundary";
import { ChatPane } from "../chat/ChatPane";
import { ResizeHandle } from "./ResizeHandle";
import { useAppearanceStore } from "../lib/appearanceStore";
import {
  useLayoutStore,
  LEFT_RAIL_MIN,
  LEFT_RAIL_MAX,
  RIGHT_DOCK_MIN,
  RIGHT_DOCK_MAX,
} from "../lib/layoutStore";

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
//
// overflow-y-hidden beside it is not redundant. CSS computes the other
// axis to `auto` whenever one axis is not `visible`, so overflow-x-auto
// alone had silently made this row vertically scrollable as well. That
// turned any overflow inside a panel into a scroll of the WHOLE row:
// with the instrument panel's sections tall enough to exceed it, the
// sidebar and the chat pane were dragged up out of the viewport and left
// a black band along the bottom of the window. A panel is responsible for
// scrolling its own content (RightDock now does, and its comment explains
// what was overflowing); the row itself must never scroll on either axis
// for that reason.
export function ShellLayout() {
  const {
    leftRailCollapsed,
    rightDockCollapsed,
    leftRailWidth,
    rightDockWidth,
    setLeftRailWidth,
    setRightDockWidth,
  } = useLayoutStore();
  // Panel widths are stored in design pixels and rendered as rem, so they grow
  // with the text size; the drag handles need the same factor to stay 1:1 with
  // the pointer.
  const fontScale = useAppearanceStore((s) => s.fontScale);

  // The shell is now exactly the three-panel row. There used to be an account
  // strip above it holding the username, Account, Admin and Log out; those
  // moved into LeftRail's cogwheel (see UserMenu.tsx), which reclaims a whole
  // row of vertical height on every screen. The row keeps `relative` because
  // ChatPane's "jump to latest" pill positions against it, and min-h-0 so the
  // panels' own scroll containers still bound correctly instead of growing the
  // row past the viewport.
  return (
    <div className="flex h-full w-full flex-col">
      <div className="relative flex min-h-0 w-full flex-1 overflow-x-auto overflow-y-hidden">
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
            scale={fontScale}
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
            scale={fontScale}
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

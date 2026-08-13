import { LeftRail } from "./LeftRail";
import { RightDock } from "./RightDock";
import { ChatPane } from "../chat/ChatPane";

// The fixed-viewport app shell: html/body/#root are height:100dvh with
// overflow:hidden (see index.css) so the PAGE itself never scrolls -- only
// the three regions below (chat's message list, and the right dock's
// molecule/jobs panels) scroll independently. This is the actual fix for
// the "scroll all the way up/down to see X" complaint the rewrite was
// asked to solve, not a cosmetic choice.
export function ShellLayout() {
  return (
    <div className="flex h-full w-full">
      <LeftRail />
      <ChatPane />
      <RightDock />
    </div>
  );
}

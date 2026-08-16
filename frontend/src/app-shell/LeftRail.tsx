import { MessageSquare, BookOpen, PanelLeftClose, PanelLeftOpen, HelpCircle } from "lucide-react";
import { useState } from "react";
import { useLayoutStore } from "../lib/layoutStore";
import { ConversationList } from "../chat/ConversationList";
import { KbSection } from "../kb/KbSection";
import { HelpFlyout } from "./HelpFlyout";
import { PanelErrorBoundary } from "./PanelErrorBoundary";

export function LeftRail() {
  const { leftRailCollapsed, toggleLeftRail } = useLayoutStore();
  const [helpOpen, setHelpOpen] = useState(false);

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
        </div>
      </div>
    );
  }

  return (
    <div className="flex w-72 shrink-0 flex-col border-r border-border bg-surface">
      <div className="flex items-center justify-between border-b border-border px-3 py-2">
        <span className="text-sm font-semibold">QM Calculation Agent</span>
        <div className="flex items-center gap-1">
          <button
            onClick={() => setHelpOpen(true)}
            className="rounded p-1.5 text-text-muted hover:bg-surface-raised hover:text-text"
            title="Help"
          >
            <HelpCircle size={15} />
          </button>
          <button
            onClick={toggleLeftRail}
            className="rounded p-1.5 text-text-muted hover:bg-surface-raised hover:text-text"
            title="Collapse sidebar"
          >
            <PanelLeftClose size={15} />
          </button>
        </div>
      </div>
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
      {helpOpen && <HelpFlyout open={helpOpen} onClose={() => setHelpOpen(false)} />}
    </div>
  );
}

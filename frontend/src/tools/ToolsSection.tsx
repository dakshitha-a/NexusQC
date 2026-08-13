import { useState } from "react";
import { Trash2 } from "lucide-react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { CollapsibleSection } from "../app-shell/CollapsibleSection";
import { toolsQueryKey, useToolsQuery } from "../lib/queries";
import * as api from "../lib/api";

// Creation goes through the chat approval flow (create_tool's interrupt),
// not this panel -- see JobApprovalCard/ToolApprovalCard.
export function ToolsSection() {
  const [collapsed, setCollapsed] = useState(false);
  const toolsQuery = useToolsQuery();
  const queryClient = useQueryClient();

  const deleteMutation = useMutation({
    mutationFn: (name: string) => api.deleteTool(name),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: toolsQueryKey }),
  });

  const tools = toolsQuery.data ?? [];

  return (
    <CollapsibleSection title="Agent tools" collapsed={collapsed} onToggle={() => setCollapsed((c) => !c)}>
      <div className="flex flex-col px-3 pb-2">
        {tools.map((t) => (
          <div key={t.name} className="group flex items-center gap-1.5 py-0.5 text-xs">
            <div className="min-w-0 flex-1 truncate text-text-muted" title={t.description}>
              <span className="font-mono text-text">{t.name}</span> — {t.description}
            </div>
            <button
              onClick={() => deleteMutation.mutate(t.name)}
              className="shrink-0 rounded p-0.5 text-text-muted opacity-0 hover:text-status-failed group-hover:opacity-100"
              title="Remove"
            >
              <Trash2 size={11} />
            </button>
          </div>
        ))}
        {tools.length === 0 && !toolsQuery.isLoading && (
          <div className="py-1 text-xs text-text-muted">No dynamic tools registered yet.</div>
        )}
      </div>
    </CollapsibleSection>
  );
}

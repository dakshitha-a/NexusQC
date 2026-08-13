import { useState } from "react";
import { AlertTriangle, RotateCcw } from "lucide-react";
import { useMutation } from "@tanstack/react-query";
import * as api from "../lib/api";
import type { PendingApproval } from "../lib/api";

export function ToolApprovalCard({ pending, threadId }: { pending: PendingApproval; threadId: string }) {
  const originalCode = (pending.code as string) ?? "";
  const [code, setCode] = useState(originalCode);
  const edited = code !== originalCode;

  const approveMutation = useMutation({
    mutationFn: (approved: boolean) => api.approveTool(threadId, approved, code),
  });

  return (
    <div className="flex justify-start">
      <div className="w-full max-w-[85%] rounded-lg border border-accent/40 bg-surface p-3.5 text-sm">
        <div className="mb-1 font-medium text-text">
          Approve new tool: <span className="font-mono">{pending.tool_name as string}</span>
        </div>
        <div className="mb-2 text-xs text-text-muted">{pending.description as string}</div>
        {(pending.param_description as string) && (
          <div className="mb-2 text-xs text-text-muted">Params: {pending.param_description as string}</div>
        )}

        <div className="mb-2 flex items-center gap-1.5 rounded border border-status-running/40 bg-status-running/10 px-2 py-1 text-[11px] text-status-running">
          <AlertTriangle size={12} />
          Runs subprocess-isolated with full filesystem access -- not a security sandbox. Review before approving.
        </div>

        <textarea
          value={code}
          onChange={(e) => setCode(e.target.value)}
          rows={14}
          className="mb-2 w-full resize-y rounded border border-border bg-bg p-2 font-mono text-[11.5px] text-text outline-none focus:border-accent"
        />

        <div className="flex items-center gap-2">
          <button
            onClick={() => approveMutation.mutate(true)}
            disabled={approveMutation.isPending}
            className="rounded bg-accent px-3 py-1.5 text-xs font-medium text-white disabled:opacity-40"
          >
            {edited ? "Register edited" : "Approve & register"}
          </button>
          <button
            onClick={() => approveMutation.mutate(false)}
            disabled={approveMutation.isPending}
            className="rounded border border-border px-3 py-1.5 text-xs text-text-muted hover:text-text disabled:opacity-40"
          >
            Reject
          </button>
          {edited && (
            <button
              onClick={() => setCode(originalCode)}
              className="flex items-center gap-1 text-[11px] text-text-muted hover:text-text"
            >
              <RotateCcw size={11} />
              Reset to generated
            </button>
          )}
        </div>
        {approveMutation.isError && (
          <div className="mt-2 text-xs text-status-failed">{String(approveMutation.error)}</div>
        )}
      </div>
    </div>
  );
}

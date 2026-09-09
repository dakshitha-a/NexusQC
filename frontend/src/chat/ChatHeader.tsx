import { useState } from "react";
import { Loader2, Pencil } from "lucide-react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useActiveThreadStore } from "../lib/activeThreadStore";
import { threadsQueryKey, useThreadsQuery, useJobsQuery } from "../lib/queries";
import * as api from "../lib/api";

/**
 * Which conversation you are in, and whether anything is running in it.
 *
 * The chat pane had no header at all. The only place a conversation's name
 * appeared was its row in the sidebar, so with the sidebar collapsed -- a
 * state that persists across reloads -- the app could not tell you which of
 * your conversations you were reading. Renaming had the same problem: it was
 * a double-click on that one row and nowhere else.
 *
 * The running-jobs chip is here rather than only in the instrument panel
 * because the panel can be collapsed too, and "is my calculation still going"
 * is the question this app exists to answer.
 */
export function ChatHeader() {
  const { activeThreadId } = useActiveThreadStore();
  const threadsQuery = useThreadsQuery();
  // This conversation's own jobs, not the cross-conversation list: JobRow
  // carries no thread id, and the per-thread query is what JobsPanel uses.
  const jobsQuery = useJobsQuery(activeThreadId);
  const queryClient = useQueryClient();
  const [renaming, setRenaming] = useState(false);
  const [value, setValue] = useState("");

  const renameMutation = useMutation({
    mutationFn: ({ id, label }: { id: string; label: string }) => api.renameThread(id, label),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: threadsQueryKey }),
  });

  const thread = (threadsQuery.data ?? []).find((t) => t.thread_id === activeThreadId);
  if (!thread) return null;

  const running = (jobsQuery.data ?? []).filter((j) => j.status === "running" || j.status === "pending");

  const startRename = () => {
    setValue(thread.label);
    setRenaming(true);
  };

  return (
    <div
      className="flex shrink-0 items-center gap-2 border-b border-border px-4 py-2"
      data-testid="chat-header"
    >
      {renaming ? (
        <input
          autoFocus
          value={value}
          onFocus={(e) => e.currentTarget.select()}
          onChange={(e) => setValue(e.target.value)}
          onBlur={() => {
            if (value.trim() && value.trim() !== thread.label) {
              renameMutation.mutate({ id: thread.thread_id, label: value.trim() });
            }
            setRenaming(false);
          }}
          onKeyDown={(e) => {
            if (e.key === "Enter") e.currentTarget.blur();
            if (e.key === "Escape") setRenaming(false);
          }}
          data-testid="chat-header-rename-input"
          className="min-w-0 flex-1 rounded border border-border bg-surface px-1.5 py-0.5 text-sm text-text outline-none"
        />
      ) : (
        <button
          onDoubleClick={startRename}
          onClick={startRename}
          data-testid="chat-header-title"
          title={`${thread.label} (click to rename)`}
          className="group flex min-w-0 flex-1 items-center gap-1.5 text-left"
        >
          <span className="truncate text-sm font-medium text-text">{thread.label}</span>
          <Pencil
            size={11}
            className="shrink-0 text-text-muted opacity-0 transition-opacity group-hover:opacity-100"
          />
        </button>
      )}
      {running.length > 0 && (
        <span
          data-testid="chat-header-running"
          title={running.map((j) => j.label || j.job_id).join("\n")}
          className="flex shrink-0 items-center gap-1.5 rounded-full border border-status-running/40 bg-status-running/10 px-2 py-0.5 text-3xs text-status-running"
        >
          <Loader2 size={10} className="animate-spin" />
          {running.length} running
        </span>
      )}
    </div>
  );
}

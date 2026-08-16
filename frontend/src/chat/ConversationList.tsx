import { useState } from "react";
import { Plus, Trash2, Pin, PinOff, Pencil } from "lucide-react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useActiveThreadStore } from "../lib/activeThreadStore";
import { threadsQueryKey, useThreadsQuery } from "../lib/queries";
import * as api from "../lib/api";
import type { ThreadSummary } from "../lib/api";

function relativeTime(epochSeconds: number): string {
  const diffSec = Date.now() / 1000 - epochSeconds;
  if (diffSec < 60) return "just now";
  if (diffSec < 3600) return `${Math.floor(diffSec / 60)}m ago`;
  if (diffSec < 86400) return `${Math.floor(diffSec / 3600)}h ago`;
  return `${Math.floor(diffSec / 86400)}d ago`;
}

export function ConversationList() {
  const { activeThreadId, setActiveThreadId } = useActiveThreadStore();
  const threadsQuery = useThreadsQuery();
  const queryClient = useQueryClient();
  const [renamingId, setRenamingId] = useState<string | null>(null);
  const [renameValue, setRenameValue] = useState("");

  const invalidate = () => queryClient.invalidateQueries({ queryKey: threadsQueryKey });

  const createMutation = useMutation({
    mutationFn: () => api.createThread(),
    onSuccess: (thread) => {
      // Seed the cache with the new thread *before* switching to it: the
      // thread-selection effect in useActiveThreadController treats an
      // activeThreadId absent from the cached thread list as stale (e.g. a
      // deleted thread) and reverts to the most-recently-active one it does
      // recognize -- if setActiveThreadId ran first, that effect would see
      // the still-stale (pre-invalidation) list, decide this brand-new
      // thread "doesn't exist yet," and immediately snap back to whichever
      // conversation was active before, silently undoing this switch
      // (confirmed empirically: activeThreadId never left the old thread).
      queryClient.setQueryData(threadsQueryKey, (old: ThreadSummary[] | undefined) => [thread, ...(old ?? [])]);
      setActiveThreadId(thread.thread_id);
      invalidate();
    },
  });

  const renameMutation = useMutation({
    mutationFn: ({ id, label }: { id: string; label: string }) => api.renameThread(id, label),
    onSuccess: invalidate,
  });

  const pinMutation = useMutation({
    mutationFn: ({ id, pinned }: { id: string; pinned: boolean }) => api.setThreadPinned(id, pinned),
    onSuccess: invalidate,
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => api.deleteThread(id),
    onSuccess: (_data, id) => {
      invalidate();
      if (activeThreadId === id) setActiveThreadId(null);
    },
  });

  const threads = threadsQuery.data ?? [];

  return (
    <div className="flex flex-col py-2">
      <div className="flex items-center justify-between px-3 pb-1">
        <span className="text-xs font-medium uppercase tracking-wide text-text-muted">Conversations</span>
        <button
          onClick={() => createMutation.mutate()}
          className="rounded p-1 text-text-muted hover:bg-surface-raised hover:text-text"
          title="New conversation"
        >
          <Plus size={14} />
        </button>
      </div>
      {createMutation.isError && (
        <div className="px-3 pb-1 text-[11px] text-status-failed">
          Couldn't create a new conversation: {String(createMutation.error)}
        </div>
      )}

      <div className="flex flex-col">
        {threads.map((t) => (
          <div
            key={t.thread_id}
            className={`group flex items-center gap-1.5 px-3 py-1.5 cursor-pointer ${
              t.thread_id === activeThreadId ? "bg-accent-muted" : "hover:bg-surface-raised"
            }`}
            onClick={() => setActiveThreadId(t.thread_id)}
          >
            {renamingId === t.thread_id ? (
              <input
                autoFocus
                value={renameValue}
                onFocus={(e) => e.currentTarget.select()}
                onChange={(e) => setRenameValue(e.target.value)}
                onClick={(e) => e.stopPropagation()}
                onBlur={() => {
                  if (renameValue.trim()) renameMutation.mutate({ id: t.thread_id, label: renameValue.trim() });
                  setRenamingId(null);
                }}
                onKeyDown={(e) => {
                  if (e.key === "Enter") e.currentTarget.blur();
                  if (e.key === "Escape") setRenamingId(null);
                }}
                className="min-w-0 flex-1 rounded border border-border bg-surface px-1.5 py-0.5 text-sm text-text outline-none"
              />
            ) : (
              <div
                className="min-w-0 flex-1"
                onDoubleClick={(e) => {
                  e.stopPropagation();
                  setRenamingId(t.thread_id);
                  setRenameValue(t.label);
                }}
              >
                <div className="flex items-center gap-1 truncate text-sm text-text">
                  {t.pinned && <Pin size={11} className="shrink-0 fill-current text-accent" />}
                  <span className="truncate">{t.label}</span>
                </div>
                <div className="text-[11px] text-text-muted">{relativeTime(t.last_active_at)}</div>
                {renameMutation.isError && renameMutation.variables?.id === t.thread_id && (
                  <div className="text-[11px] text-status-failed">Rename failed: {String(renameMutation.error)}</div>
                )}
                {pinMutation.isError && pinMutation.variables?.id === t.thread_id && (
                  <div className="text-[11px] text-status-failed">
                    {t.pinned ? "Unpin" : "Pin"} failed: {String(pinMutation.error)}
                  </div>
                )}
                {deleteMutation.isError && deleteMutation.variables === t.thread_id && (
                  <div className="text-[11px] text-status-failed">Delete failed: {String(deleteMutation.error)}</div>
                )}
              </div>
            )}
            {renamingId !== t.thread_id && (
              <>
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    setRenamingId(t.thread_id);
                    setRenameValue(t.label);
                  }}
                  className="shrink-0 rounded p-1 text-text-muted opacity-0 hover:bg-surface-raised hover:text-text group-hover:opacity-100"
                  title="Rename conversation"
                >
                  <Pencil size={13} />
                </button>
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    pinMutation.mutate({ id: t.thread_id, pinned: !t.pinned });
                  }}
                  className={`shrink-0 rounded p-1 hover:bg-surface-raised hover:text-text ${
                    t.pinned ? "text-accent" : "text-text-muted opacity-0 group-hover:opacity-100"
                  }`}
                  title={t.pinned ? "Unpin conversation" : "Pin conversation"}
                >
                  {t.pinned ? <PinOff size={13} /> : <Pin size={13} />}
                </button>
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    deleteMutation.mutate(t.thread_id);
                  }}
                  className="shrink-0 rounded p-1 text-text-muted opacity-0 hover:bg-surface-raised hover:text-status-failed group-hover:opacity-100"
                  title="Delete conversation"
                >
                  <Trash2 size={13} />
                </button>
              </>
            )}
          </div>
        ))}
        {threadsQuery.isLoading && (
          <div className="flex flex-col gap-1 px-3 py-1.5">
            {[0, 1, 2].map((i) => (
              <div key={i} className="skeleton-shimmer h-8 rounded" />
            ))}
          </div>
        )}
        {threads.length === 0 && !threadsQuery.isLoading && (
          <div className="px-3 py-1.5 text-xs text-text-muted">No conversations yet.</div>
        )}
      </div>
    </div>
  );
}

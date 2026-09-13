import { useMemo, useState } from "react";
import { Plus, Trash2, Pin, PinOff, Pencil } from "lucide-react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useActiveThreadStore } from "../lib/activeThreadStore";
import { threadsQueryKey, useThreadsQuery } from "../lib/queries";
import { fuzzyRecordScore } from "../lib/fuzzy";
import { SearchField } from "../app-shell/SearchField";
import * as api from "../lib/api";
import { relativeTime } from "../lib/relativeTime";
import type { ThreadSummary } from "../lib/api";
import { rowProps } from "../lib/rowProps";


/**
 * The conversation list, which owns the sidebar's scroll.
 *
 * ## The bug this shape fixes
 *
 * This used to be a plain `flex flex-col` with no height cap and no scroll
 * container of its own, inside a sidebar whose single `overflow-y-auto`
 * wrapped all five sections at once. So a long list simply grew, and the
 * Knowledge base, Files, Projects and Shared-with-me headers underneath it
 * were pushed off the bottom of the screen. At a dozen conversations they were
 * out of sight; there was no way back to them except deleting conversations or
 * collapsing the whole sidebar. Ten conversations was enough to do it at the
 * default text size, and five at the largest.
 *
 * The instrument dock had already solved exactly this, twice, and the reasons
 * are written up in RightDock.tsx: the sections that are content-sized are
 * `shrink-0` with a `max-h` cap and scroll internally past it, and exactly one
 * child is `flex-1` with a `min-h` floor so it takes the remaining space
 * without being squeezed to nothing. This is that arrangement, with the
 * conversation list as the flex-1 child, since it is what the sidebar is
 * primarily for.
 *
 * ## The filter
 *
 * Once the list is bounded it is scrollable, and once it is scrollable it
 * needs a way to get to a conversation without scrolling. It reuses
 * `fuzzyRecordScore`, the same matcher the job manager searches with, so
 * "cscf" finds "Run a CASSCF on butadiene" here exactly as it does there.
 */
export function ConversationList() {
  const { activeThreadId, setActiveThreadId } = useActiveThreadStore();
  const threadsQuery = useThreadsQuery();
  const queryClient = useQueryClient();
  const [renamingId, setRenamingId] = useState<string | null>(null);
  const [renameValue, setRenameValue] = useState("");
  const [query, setQuery] = useState("");
  const [searchOpen, setSearchOpen] = useState(false);

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
      // A new conversation that does not match the filter in force would
      // otherwise be created into an empty list.
      setQuery("");
      setSearchOpen(false);
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

  const threads = useMemo(() => threadsQuery.data ?? [], [threadsQuery.data]);

  // Ranked while a query is active, left in the server's order otherwise --
  // which is most-recent-first with pinned conversations lifted to the top,
  // and is what someone scanning an unfiltered list expects.
  const shown = useMemo(() => {
    const q = query.trim();
    if (!q) return threads;
    return threads
      .map((t) => ({ t, score: fuzzyRecordScore([{ text: t.label, weight: 1 }], q) }))
      .filter((r): r is { t: ThreadSummary; score: number } => r.score !== null)
      .sort((a, b) => b.score - a.score)
      .map((r) => r.t);
  }, [threads, query]);

  return (
    // flex-1 with a floor, and its own scroll container: see the note above.
    // min-h-40 is what stops it being squeezed to zero when every section
    // below is expanded, which is the failure mode the instrument dock hit.
    <div
      data-testid="conversation-list"
      className="flex min-h-40 min-w-0 flex-1 flex-col overflow-hidden"
    >
      <div className="flex shrink-0 items-center gap-1.5 px-3 py-2">
        {!searchOpen && (
          <span className="min-w-0 flex-1 truncate text-xs font-medium uppercase tracking-wide text-text-muted">
            Conversations
            {threads.length > 0 && (
              <span className="ml-1.5 tabular-nums text-text-muted/70">{threads.length}</span>
            )}
          </span>
        )}
        <SearchField
          value={query}
          onChange={setQuery}
          open={searchOpen}
          onOpenChange={setSearchOpen}
          placeholder="Search conversations"
          testId="conversation-search"
          countLabel={query ? `${shown.length}/${threads.length}` : undefined}
        />
        <button
          onClick={() => createMutation.mutate()}
          data-testid="conversation-new"
          className="shrink-0 rounded p-1 text-text-muted transition-colors hover:bg-surface-raised hover:text-text"
          title="New conversation"
          aria-label="New conversation"
        >
          <Plus size={14} />
        </button>
      </div>
      {createMutation.isError && (
        <div className="shrink-0 px-3 pb-1 text-2xs text-status-failed">
          Couldn't create a new conversation: {String(createMutation.error)}
        </div>
      )}

      <div className="flex min-h-0 flex-1 flex-col overflow-y-auto" data-testid="conversation-scroll">
        {shown.map((t) => {
          const active = t.thread_id === activeThreadId;
          const keys = rowProps(() => setActiveThreadId(t.thread_id), { kind: "button" });
          return (
            <div
              key={t.thread_id}
              data-testid={`conversation-row-${t.thread_id}`}
              // The hairline marks the conversation you are in. The wash
              // behind it is much fainter than the flat accent-muted tint this
              // replaced, because a 2px bar alone is easy to lose in a long
              // list and a full tint says "selected" without saying anything
              // else.
              className={`group flex cursor-pointer items-center gap-1.5 px-3 py-1.5 transition-colors ${
                active ? "hairline bg-accent-wash" : "hover:bg-surface-raised"
              } ${keys.className}`}
              onClick={() => setActiveThreadId(t.thread_id)}
              tabIndex={keys.tabIndex}
              role={keys.role}
              aria-current={active ? "true" : undefined}
              onKeyDown={keys.onKeyDown}
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
                  className="min-w-0 flex-1 rounded border border-border bg-surface px-1.5 py-0.5 text-xs text-text outline-none"
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
                  <div className="flex items-center gap-1 truncate text-xs text-text">
                    {t.pinned && <Pin size={11} className="shrink-0 fill-current text-accent" />}
                    <span className="truncate">{t.label}</span>
                  </div>
                  <div className="text-3xs text-text-muted">{relativeTime(t.last_active_at)}</div>
                  {renameMutation.isError && renameMutation.variables?.id === t.thread_id && (
                    <div className="text-3xs text-status-failed">Rename failed: {String(renameMutation.error)}</div>
                  )}
                  {pinMutation.isError && pinMutation.variables?.id === t.thread_id && (
                    <div className="text-3xs text-status-failed">
                      {t.pinned ? "Unpin" : "Pin"} failed: {String(pinMutation.error)}
                    </div>
                  )}
                  {deleteMutation.isError && deleteMutation.variables === t.thread_id && (
                    <div className="text-3xs text-status-failed">Delete failed: {String(deleteMutation.error)}</div>
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
                    className="shrink-0 rounded p-1 text-text-muted opacity-0 transition-opacity hover:bg-surface-raised hover:text-text focus-visible:opacity-100 group-hover:opacity-100"
                    title="Rename conversation"
                  >
                    <Pencil size={13} />
                  </button>
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      pinMutation.mutate({ id: t.thread_id, pinned: !t.pinned });
                    }}
                    className={`shrink-0 rounded p-1 transition-opacity hover:bg-surface-raised hover:text-text ${
                      t.pinned
                        ? "text-accent"
                        : "text-text-muted opacity-0 focus-visible:opacity-100 group-hover:opacity-100"
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
                    className="shrink-0 rounded p-1 text-text-muted opacity-0 transition-opacity hover:bg-surface-raised hover:text-status-failed focus-visible:opacity-100 group-hover:opacity-100"
                    title="Delete conversation"
                  >
                    <Trash2 size={13} />
                  </button>
                </>
              )}
            </div>
          );
        })}
        {threadsQuery.isLoading && (
          <div className="flex flex-col gap-1 px-3 py-1.5">
            {[0, 1, 2].map((i) => (
              <div key={i} className="skeleton-shimmer h-8 rounded" />
            ))}
          </div>
        )}
        {shown.length === 0 && !threadsQuery.isLoading && (
          <div className="px-3 py-1.5 text-xs text-text-muted" data-testid="conversation-empty">
            {query ? "No conversation matches that." : "No conversations yet. Press + to start one."}
          </div>
        )}
      </div>
    </div>
  );
}

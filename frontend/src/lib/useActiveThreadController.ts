import { useEffect } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useActiveThreadStore } from "./activeThreadStore";
import { useChatStore } from "./chatStore";
import { threadsQueryKey, useThreadsQuery } from "./queries";
import * as api from "./api";
import type { ThreadSummary } from "./api";
import { useThreadEvents } from "./sse";

/** Owns the "which conversation is open" lifecycle: picks the most
 * recently active one on load, creates a fresh one if none exist yet or
 * the persisted selection was deleted, loads that thread's message
 * history into the chat store whenever it changes, and keeps the SSE
 * subscription pointed at it. Call once near the top of the chat UI --
 * other components (e.g. ConversationList) read/set the active thread
 * via useActiveThreadStore directly rather than through this hook, since
 * Zustand state is already global. */
export function useActiveThreadController() {
  const { activeThreadId, setActiveThreadId } = useActiveThreadStore();
  const threadsQuery = useThreadsQuery();
  const queryClient = useQueryClient();
  const loadThread = useChatStore((s) => s.loadThread);

  const createThreadMutation = useMutation({
    mutationFn: () => api.createThread(),
    onSuccess: (thread) => {
      // Seed the cache before switching -- see the matching comment in
      // ConversationList.tsx's createMutation for why: this effect below
      // re-runs on the activeThreadId change this triggers, and would
      // otherwise see the still-empty pre-invalidation thread list, decide
      // the brand new thread "doesn't exist," and mutate() a second thread.
      queryClient.setQueryData(threadsQueryKey, (old: ThreadSummary[] | undefined) => [thread, ...(old ?? [])]);
      setActiveThreadId(thread.thread_id);
      queryClient.invalidateQueries({ queryKey: threadsQueryKey });
    },
  });

  useEffect(() => {
    if (!threadsQuery.isSuccess) return;
    const threads = threadsQuery.data;
    const stillExists = activeThreadId && threads.some((t) => t.thread_id === activeThreadId);
    if (stillExists) return;
    if (threads.length > 0) {
      setActiveThreadId(threads[0].thread_id);
    } else if (!createThreadMutation.isPending) {
      createThreadMutation.mutate();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [threadsQuery.isSuccess, threadsQuery.data, activeThreadId]);

  useEffect(() => {
    if (!activeThreadId) return;
    let cancelled = false;
    // Clear to this thread's (still-unknown) content immediately, before the
    // state fetch below resolves: without this, the store keeps whatever
    // the *previous* thread left behind for as long as this fetch takes
    // (confirmed empirically to be long enough to observe -- several
    // hundred ms), so a conversation switch would visibly flash the old
    // conversation's messages/molecule under the newly-active thread's
    // identity until the real data arrives.
    loadThread(activeThreadId, [], null, null);
    api.getThreadState(activeThreadId).then((state) => {
      if (cancelled) return;
      loadThread(activeThreadId, state.messages, state.pending_approval, state.molecule);
    });
    return () => {
      cancelled = true;
    };
  }, [activeThreadId, loadThread]);

  useThreadEvents(activeThreadId);

  return { activeThreadId, setActiveThreadId, createThread: () => createThreadMutation.mutate() };
}

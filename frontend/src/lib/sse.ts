import { useEffect } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useChatStore } from "./chatStore";
import { useActiveThreadStore } from "./activeThreadStore";
import { getThreadState } from "./api";

/** Subscribes to GET /api/threads/{id}/events for the active thread and
 * fans events out to the chat store (token/agent_step/message/interrupt/
 * turn_complete/error) and TanStack Query's cache (job_update, plus
 * invalidating the jobs list and thread list -- which reorders by
 * last_active_at -- on turn_complete). On turn_complete this also
 * refetches GET /state once to pick up the active molecule -- no SSE
 * event type carries molecule changes directly (unlike active_job_ids,
 * which every invoke_turn()/resume_turn() caller mirrors into the thread
 * registry), so a plain state refetch on each completed turn is the
 * simplest way to keep it live, and is cheap since it's a single read of
 * already-checkpointed state. One EventSource per mounted thread; torn
 * down and reopened whenever threadId changes. EventSource retries a
 * dropped connection on its own with no code needed here. */
export function useThreadEvents(threadId: string | null) {
  const queryClient = useQueryClient();
  const applyEvent = useChatStore((s) => s.applyEvent);
  const setMolecule = useChatStore((s) => s.setMolecule);
  const setMoleculeFrames = useChatStore((s) => s.setMoleculeFrames);
  const setSseConnected = useChatStore((s) => s.setSseConnected);

  useEffect(() => {
    if (!threadId) return;
    // Checked (not a closure-captured boolean) at the moment each event/
    // promise actually resolves, since relying on effect-cleanup timing
    // alone isn't tight enough: a duplicate or delayed server-sent event
    // (this app's agent turn loop has a documented tendency to emit
    // near-duplicate completion signals) can still be in flight through
    // this exact connection at the instant the user switches conversations,
    // arriving a beat after React re-renders with a new activeThreadId but
    // before this effect's cleanup has torn the connection down. Comparing
    // against the live store value catches that regardless of why the
    // stale event showed up, rather than trying to reason about exactly
    // when cleanup runs relative to in-flight browser/network events.
    const isStale = () => useActiveThreadStore.getState().activeThreadId !== threadId;
    setSseConnected(false);
    const es = new EventSource(`/api/threads/${threadId}/events`);
    // The server sends a leading ": connected\n\n" comment as soon as the
    // stream opens (see server/sse.py's event_stream) specifically so
    // there's an immediate, real signal to key readiness off of --
    // EventSource's own onopen already fires once the HTTP response
    // headers arrive, which for a streaming response is at least as early
    // and just as reliable, so onopen is used directly here.
    es.onopen = () => {
      if (!isStale()) setSseConnected(true);
    };
    es.onerror = () => {
      if (!isStale()) setSseConnected(false);
    }; // EventSource retries the connection itself; onopen fires again on success

    const listen = (type: string, handler: (data: Record<string, unknown>) => void) => {
      const wrapped = (e: Event) => {
        if (isStale()) return;
        handler(JSON.parse((e as MessageEvent).data));
      };
      es.addEventListener(type, wrapped);
      return () => es.removeEventListener(type, wrapped);
    };

    const cleanups = [
      listen("token", (data) => applyEvent(data as { type: string })),
      listen("agent_step", (data) => applyEvent(data as { type: string })),
      listen("message", (data) => applyEvent(data as { type: string })),
      listen("interrupt", (data) => applyEvent(data as { type: string })),
      // Emitted by job_watcher before it starts a turn nobody typed, so the
      // UI can say the conversation is busy instead of looking idle while
      // that turn holds the thread's lock. See backgroundTurn in chatStore.
      listen("turn_start", (data) => applyEvent(data as { type: string })),
      listen("error", (data) => applyEvent(data as { type: string })),
      listen("turn_complete", (data) => {
        applyEvent(data as { type: string });
        queryClient.invalidateQueries({ queryKey: ["jobs", threadId] });
        queryClient.invalidateQueries({ queryKey: ["threads"] });
        getThreadState(threadId).then((state) => {
          if (!isStale()) {
            setMolecule(state.molecule);
            setMoleculeFrames(state.molecule_frames);
          }
        });
      }),
      listen("job_update", (data) => {
        const jobId = data.job_id as string;
        // Invalidate (not setQueryData-patch) -- a job that completes while
        // its JobDetailDrawer is open must refetch its full record (summary,
        // artifacts, error), not just flip its status label while summary/
        // artifacts silently stay whatever was last fetched (confirmed real:
        // useJobQuery has no refetchInterval and ["job", jobId] was
        // invalidated nowhere else in the app before this).
        queryClient.invalidateQueries({ queryKey: ["job", jobId] });
        queryClient.invalidateQueries({ queryKey: ["jobs", threadId] });
      }),
    ];

    return () => {
      cleanups.forEach((off) => off());
      es.close();
      setSseConnected(false);
    };
  }, [threadId, applyEvent, queryClient, setMolecule, setMoleculeFrames, setSseConnected]);
}

import { useEffect } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useChatStore } from "./chatStore";
import { getThreadState, type JobRow } from "./api";

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
  const setSseConnected = useChatStore((s) => s.setSseConnected);

  useEffect(() => {
    if (!threadId) return;
    setSseConnected(false);
    const es = new EventSource(`/api/threads/${threadId}/events`);
    // The server sends a leading ": connected\n\n" comment as soon as the
    // stream opens (see server/sse.py's event_stream) specifically so
    // there's an immediate, real signal to key readiness off of --
    // EventSource's own onopen already fires once the HTTP response
    // headers arrive, which for a streaming response is at least as early
    // and just as reliable, so onopen is used directly here.
    es.onopen = () => setSseConnected(true);
    es.onerror = () => setSseConnected(false); // EventSource retries the connection itself; onopen fires again on success

    const listen = (type: string, handler: (data: Record<string, unknown>) => void) => {
      const wrapped = (e: Event) => handler(JSON.parse((e as MessageEvent).data));
      es.addEventListener(type, wrapped);
      return () => es.removeEventListener(type, wrapped);
    };

    const cleanups = [
      listen("token", (data) => applyEvent(data as { type: string })),
      listen("agent_step", (data) => applyEvent(data as { type: string })),
      listen("message", (data) => applyEvent(data as { type: string })),
      listen("interrupt", (data) => applyEvent(data as { type: string })),
      listen("error", (data) => applyEvent(data as { type: string })),
      listen("turn_complete", (data) => {
        applyEvent(data as { type: string });
        queryClient.invalidateQueries({ queryKey: ["jobs", threadId] });
        queryClient.invalidateQueries({ queryKey: ["threads"] });
        getThreadState(threadId).then((state) => setMolecule(state.molecule));
      }),
      listen("job_update", (data) => {
        const jobId = data.job_id as string;
        queryClient.setQueryData(["job", jobId], (old: JobRow | undefined) =>
          old ? { ...old, status: data.status, message: data.message } : old,
        );
        queryClient.invalidateQueries({ queryKey: ["jobs", threadId] });
      }),
    ];

    return () => {
      cleanups.forEach((off) => off());
      es.close();
      setSseConnected(false);
    };
  }, [threadId, applyEvent, queryClient, setMolecule, setSseConnected]);
}

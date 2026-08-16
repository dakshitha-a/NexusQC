import { useEffect, useRef } from "react";
import { useJobLogQuery } from "../lib/queries";

/** tail -f style preview of a running job's raw engine output, capped to
 * the last 20 lines server-side (see get_job_log). Polls while the job is
 * running and stops the instant it isn't (see useJobLogQuery). */
export function LiveLogPanel({ jobId }: { jobId: string }) {
  const { data } = useJobLogQuery(jobId, true);
  const scrollRef = useRef<HTMLDivElement>(null);
  // Reflects the user's own scroll position as of their last scroll
  // action (or our own last auto-scroll) -- checked, not recomputed, when
  // new lines arrive, so a poll tick that appends output only snaps to
  // the bottom if the user was already there. Previously this force-set
  // scrollTop on every poll unconditionally, which stole the position of
  // anyone who'd scrolled up to read earlier output.
  const nearBottomRef = useRef(true);
  const lines = data?.lines ?? [];

  const handleScroll = () => {
    const el = scrollRef.current;
    if (!el) return;
    nearBottomRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 24;
  };

  useEffect(() => {
    const el = scrollRef.current;
    if (el && nearBottomRef.current) el.scrollTop = el.scrollHeight;
  }, [lines]);

  return (
    <div>
      <div className="mb-1.5 flex items-center gap-1.5 text-xs font-medium uppercase tracking-wide text-text-muted">
        <span className="relative flex h-1.5 w-1.5">
          <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-status-running opacity-60" />
          <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-status-running" />
        </span>
        Live output
      </div>
      <div
        ref={scrollRef}
        onScroll={handleScroll}
        className="max-h-56 overflow-y-auto rounded border border-border bg-bg p-2 font-mono text-[11px] leading-relaxed text-text-muted"
      >
        {lines.length === 0 ? (
          <div className="text-text-muted/60">Waiting for output...</div>
        ) : (
          lines.map((line, i) => (
            <div key={i} className="whitespace-pre-wrap break-all">
              {line}
            </div>
          ))
        )}
      </div>
    </div>
  );
}

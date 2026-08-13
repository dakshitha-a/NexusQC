import { useEffect, useRef } from "react";
import { useJobLogQuery } from "../lib/queries";

/** tail -f style preview of a running job's raw engine output, capped to
 * the last 20 lines server-side (see get_job_log). Polls while the job is
 * running and stops the instant it isn't (see useJobLogQuery). */
export function LiveLogPanel({ jobId }: { jobId: string }) {
  const { data } = useJobLogQuery(jobId, true);
  const scrollRef = useRef<HTMLDivElement>(null);
  const lines = data?.lines ?? [];

  useEffect(() => {
    if (scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
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

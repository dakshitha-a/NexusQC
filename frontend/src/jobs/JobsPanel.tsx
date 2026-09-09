import { EngineTag, flashColor } from "./EngineTag";
import { GitBranch } from "lucide-react";
import { useState } from "react";
import { useActiveThreadStore } from "../lib/activeThreadStore";
import { useJobsQuery } from "../lib/queries";
import { StatusDot } from "./StatusDot";
import { KillButton } from "./KillButton";
import { JobDetailDrawer } from "./JobDetailDrawer";
import { useFlashOnTerminal } from "./useFlashOnTerminal";
import { relativeTime, jobTimeTitle } from "../lib/relativeTime";
import type { CSSProperties } from "react";
import type { JobRow } from "../lib/api";


function description(job: JobRow): string {
  if (job.label) return job.label;
  // The v2 task before the runner key: "opt/min" says what was asked for,
  // where "geometry_optimization" is the name of the function that ran it.
  // Falls back for a job submitted before the taxonomy switch, which has
  // no task at all.
  if (job.task) return job.subtype ? `${job.task}/${job.subtype}` : job.task;
  return `${job.method ?? "job"}`;
}

function JobsPanelSkeleton() {
  return (
    <div className="flex flex-col gap-1 px-3 py-2">
      {[0, 1, 2].map((i) => (
        <div key={i} className="skeleton-shimmer h-8 rounded" />
      ))}
    </div>
  );
}

export function JobsPanel() {
  const { activeThreadId } = useActiveThreadStore();
  const jobsQuery = useJobsQuery(activeThreadId);
  const [selectedJobId, setSelectedJobId] = useState<string | null>(null);
  const { flashing, clear } = useFlashOnTerminal(jobsQuery.data ?? []);

  const jobs = jobsQuery.data ?? [];

  if (!activeThreadId) return null;

  if (jobsQuery.isLoading) return <JobsPanelSkeleton />;

  if (jobsQuery.isError) {
    return (
      <div className="flex-1 overflow-y-auto px-3 py-2 text-xs text-status-failed">
        Couldn't load jobs: {String(jobsQuery.error)}
      </div>
    );
  }

  if (jobs.length === 0) {
    return <div className="flex-1 overflow-y-auto px-3 py-2 text-xs text-text-muted">No jobs submitted yet in this conversation.</div>;
  }

  return (
    <div className="flex-1 overflow-y-auto">
      {/* table-fixed, not the browser default. Under auto layout a column is
          at least as wide as its widest unbreakable content, so a long job
          name (or the job id below it) widened the whole table past the
          panel, the panel grew a horizontal scrollbar, and the cancel button
          in the last column sat off-screen until you scrolled to it. Fixed
          layout makes the name column take what is left after the fixed ones
          instead of dictating the width, so the button is always in view and
          the name fades out where it runs out of room. */}
      <table className="w-full table-fixed text-xs">
        <tbody>
          {jobs.map((job) => (
            <tr
              key={job.job_id}
              onClick={() => setSelectedJobId(job.job_id)}
              data-testid={`job-row-${job.job_id}`}
              onAnimationEnd={() => clear(job.job_id)}
              // The hairline marks a job that is actually running, which is
              // the one row in this list somebody is waiting on. The flash
              // takes its colour from the status the job reached, so a
              // failure and a completion no longer look the same for the
              // 900ms that is the only notice either of them gets.
              style={{ "--flash-color": flashColor(job.status) } as CSSProperties}
              className={`cursor-pointer border-t border-border hover:bg-surface-raised ${
                flashing.has(job.job_id) ? "animate-flash-once" : ""
              }`}
            >
              {/* The hairline is on the cell, not the <tr>: a table row is
                  not a reliable positioning context for an absolutely
                  positioned pseudo-element. */}
              <td className={`w-6 py-2 pl-3 ${job.status === "running" ? "hairline hairline-live" : ""}`}>
                <StatusDot status={job.status} />
              </td>
              {/* The full name on hover, since the visible one is cut off
                  whenever it is long enough to matter. On the cell rather
                  than the first line so the id line answers to it too. */}
              <td className="min-w-0 py-2" title={description(job)}>
                <div className="fade-edge-right text-text">
                  {job.master_kind && <GitBranch size={10} className="mr-1 inline text-text-muted" />}
                  {description(job)}
                </div>
                {/* The id line carries the timestamp rather than a column of
                    its own. Under table-fixed a dedicated w-16 cell takes its
                    width straight out of the name, which is the only cell that
                    absorbs the remainder -- and this line ended well short of
                    the right edge anyway. The fade mask has to sit on the id
                    span, not on this flex wrapper, or it fades the time out
                    too. */}
                <div className="flex items-baseline gap-2">
                  <span className="fade-edge-right min-w-0 flex-1 font-mono text-3xs text-text-muted">
                    {job.job_id} &middot; <EngineTag engine={job.engine} />
                  </span>
                  <span
                    data-testid={`job-time-${job.job_id}`}
                    className="shrink-0 text-3xs tabular-nums text-text-muted"
                    title={jobTimeTitle(job)}
                  >
                    {relativeTime(job.updated_at)}
                  </span>
                </div>
              </td>
              {/* Wide enough for the two-button confirm state KillButton
                  swaps in, not just the resting single button: a fixed-layout
                  column cannot grow to fit it, so sizing this for the resting
                  width would clip the confirm/dismiss pair. */}
              <td className="w-14 py-2 pr-2">
                <div className="flex justify-end">
                  <KillButton job={job} threadId={activeThreadId} />
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      {selectedJobId && (
        <JobDetailDrawer jobId={selectedJobId} threadId={activeThreadId} onClose={() => setSelectedJobId(null)} />
      )}
    </div>
  );
}

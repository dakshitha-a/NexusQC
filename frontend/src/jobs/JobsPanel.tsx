import { useState } from "react";
import { useActiveThreadStore } from "../lib/activeThreadStore";
import { useJobsQuery } from "../lib/queries";
import { StatusDot } from "./StatusDot";
import { KillButton } from "./KillButton";
import { JobDetailDrawer } from "./JobDetailDrawer";
import type { JobRow } from "../lib/api";

function relativeTime(epochSeconds: number | null): string {
  if (!epochSeconds) return "";
  const diffSec = Date.now() / 1000 - epochSeconds;
  if (diffSec < 5) return "now";
  if (diffSec < 60) return `${Math.floor(diffSec)}s ago`;
  if (diffSec < 3600) return `${Math.floor(diffSec / 60)}m ago`;
  if (diffSec < 86400) return `${Math.floor(diffSec / 3600)}h ago`;
  return `${Math.floor(diffSec / 86400)}d ago`;
}

function description(job: JobRow): string {
  if (job.label) return job.label;
  return `${job.method ?? "job"}`;
}

export function JobsPanel() {
  const { activeThreadId } = useActiveThreadStore();
  const jobsQuery = useJobsQuery(activeThreadId);
  const [selectedJobId, setSelectedJobId] = useState<string | null>(null);

  const jobs = jobsQuery.data ?? [];

  if (!activeThreadId) return null;

  if (jobs.length === 0) {
    return <div className="flex-1 overflow-y-auto px-3 py-2 text-xs text-text-muted">No jobs submitted yet in this conversation.</div>;
  }

  return (
    <div className="flex-1 overflow-y-auto">
      <table className="w-full text-xs">
        <tbody>
          {jobs.map((job) => (
            <tr
              key={job.job_id}
              onClick={() => setSelectedJobId(job.job_id)}
              className="cursor-pointer border-t border-border hover:bg-surface-raised"
            >
              <td className="w-6 py-2 pl-3">
                <StatusDot status={job.status} />
              </td>
              <td className="min-w-0 py-2">
                <div className="truncate text-text">{description(job)}</div>
                <div className="truncate font-mono text-[10.5px] text-text-muted">
                  {job.job_id} &middot; {job.engine}
                </div>
              </td>
              <td className="w-16 whitespace-nowrap py-2 pr-1 text-right text-[10.5px] text-text-muted">
                {relativeTime(job.updated_at)}
              </td>
              <td className="w-7 py-2 pr-2">
                <KillButton job={job} threadId={activeThreadId} />
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

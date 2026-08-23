import { useState } from "react";
import { GitBranch, Paperclip } from "lucide-react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import * as api from "../lib/api";
import { jobsListQueryKey, useJobsListQuery } from "../lib/queries";
import { useAttachedJobsStore } from "../lib/attachedJobsStore";
import { StatusDot } from "./StatusDot";
import { DeleteJobButton } from "./DeleteJobButton";
import { JobDetailDrawer } from "./JobDetailDrawer";
import { useFlashOnTerminal } from "./useFlashOnTerminal";
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

// This is the persistent, cross-conversation job list (GET /api/jobs) --
// distinct from JobsPanel.tsx, which stays scoped to the active
// conversation's own jobs for the chat sidebar. Selecting rows here and
// hitting "Attach to prompt" feeds job_ids into the Composer via
// attachedJobsStore, so the user can ask the agent questions about past
// results without re-finding/re-typing job ids.
export function JobManagerPanel() {
  const jobsQuery = useJobsListQuery();
  const queryClient = useQueryClient();
  const { attachedJobs, addJob, removeJob } = useAttachedJobsStore();
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [renamingId, setRenamingId] = useState<string | null>(null);
  const [renameValue, setRenameValue] = useState("");
  const [openJobId, setOpenJobId] = useState<string | null>(null);

  const renameMutation = useMutation({
    mutationFn: ({ id, label }: { id: string; label: string }) => api.renameJob(id, label),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: jobsListQueryKey }),
  });

  const jobs = jobsQuery.data ?? [];
  const attachedIds = new Set(attachedJobs.map((j) => j.job_id));
  const { flashing, clear } = useFlashOnTerminal(jobs);

  const toggleSelected = (jobId: string) => {
    setSelected((s) => {
      const next = new Set(s);
      if (next.has(jobId)) next.delete(jobId);
      else next.add(jobId);
      return next;
    });
  };

  const attachSelected = () => {
    for (const job of jobs) {
      if (selected.has(job.job_id)) addJob({ job_id: job.job_id, label: job.label || job.job_id });
    }
    setSelected(new Set());
  };

  if (jobsQuery.isLoading) {
    return (
      <div className="flex flex-col gap-1 px-3 py-2">
        {[0, 1, 2, 3].map((i) => (
          <div key={i} className="skeleton-shimmer h-8 rounded" />
        ))}
      </div>
    );
  }

  if (jobsQuery.isError) {
    return (
      <div className="flex-1 overflow-y-auto px-3 py-2 text-xs text-status-failed">
        Couldn't load jobs: {String(jobsQuery.error)}
      </div>
    );
  }

  if (jobs.length === 0) {
    return <div className="flex-1 overflow-y-auto px-3 py-2 text-xs text-text-muted">No jobs have been run yet.</div>;
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      {attachedJobs.length > 0 && (
        <div className="flex flex-wrap gap-1 border-b border-border px-3 py-1.5">
          {attachedJobs.map((j) => (
            <span
              key={j.job_id}
              className="flex items-center gap-1 rounded-full bg-accent-muted px-2 py-0.5 text-[10.5px] text-text"
            >
              {j.label}
              <button
                onClick={() => removeJob(j.job_id)}
                data-testid={`jobmanager-detach-job-${j.job_id}`}
                className="text-text-muted hover:text-text"
                title="Detach job from prompt"
              >
                &times;
              </button>
            </span>
          ))}
        </div>
      )}
      {selected.size > 0 && (
        <div className="flex items-center justify-between border-b border-border bg-surface-raised px-3 py-1.5">
          <span className="text-[11px] text-text-muted">{selected.size} selected</span>
          <button
            onClick={attachSelected}
            className="flex items-center gap-1 rounded bg-accent px-2 py-1 text-[11px] text-white"
          >
            <Paperclip size={11} />
            Attach to prompt
          </button>
        </div>
      )}
      <div className="min-h-0 flex-1 overflow-y-auto">
        <table className="w-full text-xs">
          <tbody>
            {jobs.map((job: JobRow) => (
              <tr
                key={job.job_id}
                // The row renders the job's LABEL, not its id, so a test
                // that knows which job it seeded had no way to click that
                // job's row -- only to guess at a label that is not unique
                // across two scans of the same molecule at the same level of
                // theory. Same shape as the detach button's own testid above.
                data-testid={`jobmanager-row-${job.job_id}`}
                onClick={() => setOpenJobId(job.job_id)}
                onAnimationEnd={() => clear(job.job_id)}
                className={`cursor-pointer border-t border-border hover:bg-surface-raised ${
                  flashing.has(job.job_id) ? "animate-flash-once" : ""
                }`}
              >
                <td className="w-6 py-2 pl-3" onClick={(e) => e.stopPropagation()}>
                  <input
                    type="checkbox"
                    checked={selected.has(job.job_id)}
                    onChange={() => toggleSelected(job.job_id)}
                  />
                </td>
                <td className="w-6 py-2">
                  <StatusDot status={job.status} />
                </td>
                <td className="min-w-0 py-2">
                  {renamingId === job.job_id ? (
                    <input
                      autoFocus
                      value={renameValue}
                      onChange={(e) => setRenameValue(e.target.value)}
                      onClick={(e) => e.stopPropagation()}
                      onBlur={() => {
                        if (renameValue.trim()) renameMutation.mutate({ id: job.job_id, label: renameValue.trim() });
                        setRenamingId(null);
                      }}
                      onKeyDown={(e) => {
                        if (e.key === "Enter") e.currentTarget.blur();
                        if (e.key === "Escape") setRenamingId(null);
                      }}
                      className="w-full min-w-0 rounded border border-border bg-surface px-1 py-0.5 text-xs text-text outline-none"
                    />
                  ) : (
                    <div
                      className="truncate text-text"
                      // A double-click is preceded by two ordinary "click"
                      // events (browsers fire click, click, dblclick in
                      // sequence) -- without stopping propagation on the
                      // single click too, those bubble up to the row's own
                      // onClick and open the JobDetailDrawer mid-rename,
                      // stealing focus before the rename input ever shows.
                      onClick={(e) => e.stopPropagation()}
                      onDoubleClick={(e) => {
                        e.stopPropagation();
                        setRenamingId(job.job_id);
                        setRenameValue(job.label);
                      }}
                      title="Double-click to rename"
                    >
                      {job.master_kind && (
                        <GitBranch size={10} className="mr-1 inline text-text-muted" aria-label={job.master_kind} />
                      )}
                      {job.label}
                      {attachedIds.has(job.job_id) && <Paperclip size={10} className="ml-1 inline text-accent" />}
                    </div>
                  )}
                  <div className="truncate font-mono text-[10.5px] text-text-muted">
                    {job.job_id} &middot; {job.engine}
                  </div>
                  {renameMutation.isError && renameMutation.variables?.id === job.job_id && (
                    <div className="text-[10.5px] text-status-failed">
                      Rename failed: {String(renameMutation.error)}
                    </div>
                  )}
                </td>
                <td className="w-16 whitespace-nowrap py-2 pr-1 text-right text-[10.5px] text-text-muted">
                  {relativeTime(job.created_at)}
                </td>
                <td className="w-7 py-2 pr-2">
                  <DeleteJobButton jobId={job.job_id} disabled={job.status === "pending" || job.status === "running"} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {openJobId && <JobDetailDrawer jobId={openJobId} onClose={() => setOpenJobId(null)} />}
    </div>
  );
}

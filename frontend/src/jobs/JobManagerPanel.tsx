import { useMemo, useState } from "react";
import { GitBranch, Paperclip, Pencil, Search, X } from "lucide-react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import * as api from "../lib/api";
import { jobsListQueryKey, useJobsListQuery } from "../lib/queries";
import { useAttachedJobsStore } from "../lib/attachedJobsStore";
import { StatusDot } from "./StatusDot";
import { DeleteJobButton } from "./DeleteJobButton";
import { JobDetailDrawer } from "./JobDetailDrawer";
import { useFlashOnTerminal } from "./useFlashOnTerminal";
import { fuzzyRecordScore } from "../lib/fuzzy";
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
  const [query, setQuery] = useState("");

  const renameMutation = useMutation({
    mutationFn: ({ id, label }: { id: string; label: string }) => api.renameJob(id, label),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: jobsListQueryKey }),
  });

  const jobs = jobsQuery.data ?? [];
  const attachedIds = new Set(attachedJobs.map((j) => j.job_id));
  const { flashing, clear } = useFlashOnTerminal(jobs);

  // Fuzzy, not substring: "cscf" finds a CASSCF run and "urcas" finds
  // "uracil SP CASSCF(12,9)/...". Matched against everything the row already
  // shows, so anything readable here is searchable -- the name, the id and
  // the engine are all on screen, and status is what the dot means.
  //
  // The weights matter more than they look. Fuzzy-matching a hex job id
  // produces a lot of accidental hits for any short query, so the id is
  // deliberately the weakest field and can never outrank a real name match.
  // Results are reordered by score while a query is active, and left in the
  // list's own recency order when it is not.
  const filtered = useMemo(() => {
    if (!query.trim()) return jobs;
    const scored: { job: JobRow; score: number }[] = [];
    for (const job of jobs) {
      const score = fuzzyRecordScore(
        [
          { text: job.label ?? "", weight: 1 },
          { text: job.engine ?? "", weight: 0.8 },
          { text: job.status ?? "", weight: 0.8 },
          { text: job.job_id, weight: 0.5 },
        ],
        query,
      );
      if (score !== null) scored.push({ job, score });
    }
    scored.sort((a, b) => b.score - a.score);
    return scored.map((s) => s.job);
  }, [jobs, query]);

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

  // The list's loading/error/empty states are a variable rather than early
  // returns so the open preview below survives all three. This list polls
  // every 4s, and an errored tick sets the query's status to error while
  // keeping the data it already had -- as early returns, one dropped poll
  // swapped the whole panel, including the mounted drawer, for the error
  // line, closing a preview the user was reading through no action of theirs.
  const listBody = jobsQuery.isLoading ? (
    <div className="flex flex-col gap-1 px-3 py-2">
      {[0, 1, 2, 3].map((i) => (
        <div key={i} className="skeleton-shimmer h-8 rounded" />
      ))}
    </div>
  ) : jobsQuery.isError ? (
    <div className="flex-1 overflow-y-auto px-3 py-2 text-xs text-status-failed">
      Couldn't load jobs: {String(jobsQuery.error)}
    </div>
  ) : jobs.length === 0 ? (
    <div className="flex-1 overflow-y-auto px-3 py-2 text-xs text-text-muted">No jobs have been run yet.</div>
  ) : (
    <div className="flex min-h-0 flex-1 flex-col">
      {/* Above the attached-jobs strip and the selection bar, so the thing
          that narrows the list sits at the top of the list rather than
          moving down the panel as those two appear and disappear. */}
      <div className="border-b border-border px-3 py-1.5">
        <div className="relative">
          <Search
            size={12}
            className="pointer-events-none absolute left-2 top-1/2 -translate-y-1/2 text-text-muted"
          />
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Escape") setQuery("");
            }}
            placeholder="Search jobs"
            aria-label="Search jobs"
            data-testid="jobmanager-search"
            className="w-full rounded border border-border bg-surface py-1 pl-7 pr-6 text-xs text-text outline-none placeholder:text-text-muted focus:border-accent"
          />
          {query && (
            <button
              onClick={() => setQuery("")}
              data-testid="jobmanager-search-clear"
              title="Clear search"
              aria-label="Clear search"
              className="absolute right-1.5 top-1/2 -translate-y-1/2 rounded p-0.5 text-text-muted hover:text-text"
            >
              <X size={11} />
            </button>
          )}
        </div>
        {query && (
          <div className="pt-1 text-[10.5px] text-text-muted">
            {filtered.length} of {jobs.length} {jobs.length === 1 ? "job" : "jobs"}
          </div>
        )}
      </div>
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
        {/* table-fixed for the same reason JobsPanel.tsx is: under auto
            layout a long label sets the column's minimum width, the table
            outgrows the panel, and the delete button ends up behind a
            horizontal scrollbar. */}
        <table className="w-full table-fixed text-xs">
          <tbody>
            {filtered.length === 0 && (
              <tr>
                <td colSpan={5} className="px-3 py-3 text-xs text-text-muted"
                    data-testid="jobmanager-search-empty">
                  No jobs match that search.
                </td>
              </tr>
            )}
            {filtered.map((job: JobRow) => (
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
                      className="fade-edge-right text-text"
                      // No click handler of its own, deliberately. Renaming
                      // used to live on a double-click here, and because a
                      // double-click is preceded by two ordinary click events
                      // (browsers fire click, click, dblclick in sequence)
                      // the single click had to be swallowed to stop the
                      // drawer opening mid-rename. That made the widest and
                      // most obvious target in the row -- the job's name, a
                      // block element spanning the whole name column -- the
                      // one place a click did nothing, so opening a preview
                      // took two tries and read as lag. Renaming is a button
                      // in the action column now and the whole row opens the
                      // preview.
                      // The visible name is cut off once it is long, and this
                      // tooltip is the only place the whole of it can be read.
                      title={job.label}
                    >
                      {job.master_kind && (
                        <GitBranch size={10} className="mr-1 inline text-text-muted" aria-label={job.master_kind} />
                      )}
                      {job.label}
                      {attachedIds.has(job.job_id) && <Paperclip size={10} className="ml-1 inline text-accent" />}
                    </div>
                  )}
                  <div className="fade-edge-right font-mono text-[10.5px] text-text-muted">
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
                {/* Sized for the rename button alongside DeleteJobButton's
                    two-button confirm state, not its resting single button --
                    a fixed-layout column cannot grow to fit them the way an
                    auto one did. The cell stops click propagation for the
                    same reason the checkbox cell does: everything in it acts
                    on the row rather than opening it. */}
                <td className="w-20 py-2 pr-2" onClick={(e) => e.stopPropagation()}>
                  <div className="flex justify-end gap-0.5">
                    <button
                      onClick={() => {
                        setRenamingId(job.job_id);
                        setRenameValue(job.label);
                      }}
                      data-testid={`jobmanager-rename-${job.job_id}`}
                      className="shrink-0 rounded p-1 text-text-muted hover:bg-surface-raised hover:text-text"
                      title="Rename job"
                    >
                      <Pencil size={12} />
                    </button>
                    <DeleteJobButton
                      jobId={job.job_id}
                      disabled={job.status === "pending" || job.status === "running"}
                    />
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );

  return (
    <>
      {listBody}
      {openJobId && <JobDetailDrawer jobId={openJobId} onClose={() => setOpenJobId(null)} />}
    </>
  );
}

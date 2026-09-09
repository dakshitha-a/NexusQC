import { EngineTag, flashColor } from "./EngineTag";
import { useMemo, useState } from "react";
import { Archive, GitBranch, Inbox, Paperclip, Pencil, Send, Undo2, X } from "lucide-react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import * as api from "../lib/api";
import { jobsListQueryKey, useJobsListQuery } from "../lib/queries";
import { useAttachedJobsStore } from "../lib/attachedJobsStore";
import { AddToProjectPopover } from "../projects/AddToProjectPopover";
import { ShareDialog } from "../sharing/ShareDialog";
import { projectsQueryKey } from "../lib/queries";
import { StatusDot } from "./StatusDot";
import { DeleteJobButton } from "./DeleteJobButton";
import { JobDetailDrawer } from "./JobDetailDrawer";
import { useFlashOnTerminal } from "./useFlashOnTerminal";
import { fuzzyRecordScore } from "../lib/fuzzy";
import { useJobFilterStore } from "../lib/jobFilterStore";
import { SearchInput } from "../app-shell/SearchField";
import type { CSSProperties } from "react";
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
  // What is being shown lives in a store rather than in this component,
  // because the controls that set it are in the section's header now (see
  // JobManagerToolbar) and the header is rendered by RightDock. It is still
  // not persisted, for the reason it never was: archiving a finished study is
  // how you get it off this list, and a rail that silently came back a week
  // later showing archived jobs would just look like archiving had stopped
  // working.
  const { query, searchOpen, showArchived, statuses, engines } = useJobFilterStore();
  const { setQuery, setSearchOpen, setShowArchived, clearFilters } = useJobFilterStore();
  const jobsQuery = useJobsListQuery(showArchived);
  const queryClient = useQueryClient();
  const { attachedJobs, addJob, removeJob } = useAttachedJobsStore();
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [addingToProject, setAddingToProject] = useState(false);
  const [sharing, setSharing] = useState<{ id: string; name: string } | null>(null);
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
  // Status and engine narrow the set; the text query then ranks what is left.
  // An empty selection means "no narrowing", which is what an untouched filter
  // reads as, rather than "show nothing".
  const narrowed = useMemo(
    () =>
      jobs.filter(
        (job) =>
          (statuses.length === 0 || statuses.includes(job.status)) &&
          (engines.length === 0 || engines.includes(job.engine ?? "")),
      ),
    [jobs, statuses, engines],
  );

  const filtered = useMemo(() => {
    if (!query.trim()) return narrowed;
    const scored: { job: JobRow; score: number }[] = [];
    for (const job of narrowed) {
      const score = fuzzyRecordScore(
        [
          { text: job.label ?? "", weight: 1 },
          { text: job.engine ?? "", weight: 0.8 },
          { text: job.status ?? "", weight: 0.8 },
          // Weighted like the name, not like the id: typing a project's
          // name is a deliberate way to pull up that study's jobs, and it
          // is exactly as readable on the row as the job's own name is.
          { text: job.project_name ?? "", weight: 1 },
          { text: job.job_id, weight: 0.5 },
        ],
        query,
      );
      if (score !== null) scored.push({ job, score });
    }
    scored.sort((a, b) => b.score - a.score);
    return scored.map((s) => s.job);
  }, [narrowed, query]);

  const toggleSelected = (jobId: string) => {
    setSelected((s) => {
      const next = new Set(s);
      if (next.has(jobId)) next.delete(jobId);
      else next.add(jobId);
      return next;
    });
  };

  const unarchiveMutation = useMutation({
    mutationFn: ({ projectId, jobId }: { projectId: string; jobId: string }) =>
      api.removeProjectJobs(projectId, [jobId]),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: jobsListQueryKey });
      queryClient.invalidateQueries({ queryKey: projectsQueryKey });
    },
  });

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
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="px-3 py-2 text-xs text-text-muted" data-testid="jobmanager-empty">
        {showArchived
          ? "No jobs have been run yet."
          : "No unarchived jobs. Any finished ones are in a project archive."}
      </div>
      {/* A way back has to survive the empty state, or somebody who archived
          every job they had is left with no route to any of them from this
          panel. It is a button rather than the checkbox it used to be, to
          match the icon in the header that does the same thing. */}
      {!showArchived && (
        <button
          type="button"
          onClick={() => setShowArchived(true)}
          data-testid="jobmanager-show-archived-empty"
          aria-pressed={false}
          className="flex items-center gap-1.5 self-start rounded px-3 py-1 text-2xs text-accent hover:underline"
        >
          <Archive size={12} />
          Show archived jobs
        </button>
      )}
    </div>
  ) : (
    <div className="flex min-h-0 flex-1 flex-col">
      {/* This row used to be permanent: a search box, a "Show archived"
          checkbox, and a second row for the result count whenever a query was
          active. This is the app's only flex-1 pane, so a row spent here is
          measured in jobs you cannot see, and it was spent whether or not
          anybody was filtering. The controls are icons in the section header
          now (JobManagerToolbar); only the input itself comes back, and only
          while it is open, where it can have the full width. */}
      {searchOpen && (
        <div className="flex items-center border-b border-border px-3 py-1.5">
          <SearchInput
            value={query}
            onChange={setQuery}
            onClose={() => setSearchOpen(false)}
            placeholder="Search jobs"
            testId="jobmanager-search"
            countLabel={query ? `${filtered.length} of ${jobs.length}` : undefined}
          />
        </div>
      )}
      {/* A filter that is on but out of sight turns a short list into a bug
          report, so what is in force is always named, with one click to undo
          it. */}
      {(statuses.length > 0 || engines.length > 0) && (
        <div className="flex flex-wrap items-center gap-1 border-b border-border px-3 py-1.5">
          {[...statuses, ...engines].map((f) => (
            <span
              key={f}
              className="rounded-full bg-accent-muted px-2 py-0.5 text-3xs capitalize text-text"
              data-testid={`jobmanager-active-filter-${f}`}
            >
              {f}
            </span>
          ))}
          <button
            onClick={clearFilters}
            data-testid="jobmanager-active-filters-clear"
            className="ml-auto text-3xs text-text-muted hover:text-text"
          >
            Clear
          </button>
        </div>
      )}
      {attachedJobs.length > 0 && (
        <div className="flex flex-wrap gap-1 border-b border-border px-3 py-1.5">
          {attachedJobs.map((j) => (
            <span
              key={j.job_id}
              className="flex items-center gap-1 rounded-full bg-accent-muted px-2 py-0.5 text-3xs text-text"
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
        // `relative` so AddToProjectPopover can position against this bar
        // rather than against the panel, which scrolls under it.
        <div className="relative flex items-center justify-between border-b border-border bg-surface-raised px-3 py-1.5">
          <span className="text-2xs text-text-muted">{selected.size} selected</span>
          <div className="flex items-center gap-1">
            {/* Icon only: the two actions beside it are what this bar is
                for, and a third labelled button would crowd them at a
                narrow dock width. Unticking rows one at a time was the only
                way out of a selection before this. */}
            <button
              onClick={() => setSelected(new Set())}
              data-testid="jobmanager-clear-selection"
              title="Clear selection"
              aria-label="Clear selection"
              className="rounded border border-border p-1 text-text-muted hover:bg-surface hover:text-text"
            >
              <X size={12} />
            </button>
            <button
              onClick={() => setAddingToProject((a) => !a)}
              data-testid="jobmanager-add-to-project"
              className="flex items-center gap-1 rounded border border-border px-2 py-1 text-2xs text-text hover:bg-surface"
            >
              <Archive size={11} />
              Add to project
            </button>
            {selected.size === 1 && (
              // Offered only for a single selection. A share is one offer of
              // one thing, and a bulk gesture here would either fan out into
              // N separate inbox rows or silently invent a project to hold
              // them -- both worse than asking the user to pick one.
              // Labelled "Send a copy" rather than "Share" for two reasons:
              // it says what actually happens, and Playwright's has-text is
              // a case-insensitive SUBSTRING match, so a control named
              // "Share" would also match "Shared with me" in the rail.
              <button
                onClick={() => {
                  const id = [...selected][0];
                  const row = jobs.find((r) => r.job_id === id);
                  setSharing({ id, name: row?.label ?? id });
                }}
                data-testid="jobmanager-send-copy"
                className="flex items-center gap-1 rounded border border-border px-2 py-1 text-2xs text-text hover:bg-surface"
              >
                <Send size={11} />
                Send a copy
              </button>
            )}
            <button
              onClick={attachSelected}
              data-testid="jobmanager-attach-to-prompt"
              className="flex items-center gap-1 rounded bg-accent px-2 py-1 text-2xs text-on-accent"
            >
              <Paperclip size={11} />
              Attach to prompt
            </button>
          </div>
          {addingToProject && (
            <AddToProjectPopover
              jobIds={[...selected]}
              onClose={() => setAddingToProject(false)}
              onDone={() => {
                setAddingToProject(false);
                setSelected(new Set());
              }}
            />
          )}
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
                {/* The hairline lives on the first cell rather than on the
                    <tr>: a table row is not a reliable positioning context for
                    an absolutely positioned pseudo-element, and a cell
                    stretches to the row's full height regardless. */}
                <td
                  className={`w-6 py-2 pl-3 ${job.status === "running" ? "hairline" : ""}`}
                  onClick={(e) => e.stopPropagation()}
                >
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
                    {job.project_name && (
                      <div
                        className="fade-edge-right mt-0.5 flex items-center gap-0.5 text-3xs text-text-muted"
                        data-testid={`jobmanager-project-badge-${job.job_id}`}
                        title={`Filed into "${job.project_name}"`}
                      >
                        <Archive size={9} className="shrink-0" />
                        {job.project_name}
                      </div>
                    )}
                    {job.shared_from && (
                      // Same shape as the project badge above deliberately:
                      // icon plus 10px muted text, fade-edge-right for
                      // overflow, and the explanation in the tooltip. This
                      // is a copy the user accepted from someone else, and
                      // without the badge there is nothing to distinguish it
                      // from a job they ran themselves.
                      <div
                        className="fade-edge-right mt-0.5 flex items-center gap-0.5 text-3xs text-text-muted"
                        data-testid={`jobmanager-shared-badge-${job.job_id}`}
                        title={`A copy ${job.shared_from} sent you. It is yours now; deleting theirs does not affect it.`}
                      >
                        <Inbox size={9} className="shrink-0" />
                        from {job.shared_from}
                      </div>
                    )}
                  <div className="fade-edge-right font-mono text-3xs text-text-muted">
                    {job.job_id} &middot; <EngineTag engine={job.engine} />
                  </div>
                  {renameMutation.isError && renameMutation.variables?.id === job.job_id && (
                    <div className="text-3xs text-status-failed">
                      Rename failed: {String(renameMutation.error)}
                    </div>
                  )}
                </td>
                <td className="w-16 whitespace-nowrap py-2 pr-1 text-right text-3xs text-text-muted">
                  {relativeTime(job.created_at)}
                </td>
                {/* Sized for the rename button alongside DeleteJobButton's
                    two-button confirm state, not its resting single button --
                    a fixed-layout column cannot grow to fit them the way an
                    auto one did. The cell stops click propagation for the
                    same reason the checkbox cell does: everything in it acts
                    on the row rather than opening it. */}
                <td
                  className={`${showArchived ? "w-28" : "w-20"} py-2 pr-2`}
                  onClick={(e) => e.stopPropagation()}
                >
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
                    {job.project_id && (
                      <button
                        onClick={() =>
                          unarchiveMutation.mutate({ projectId: job.project_id!, jobId: job.job_id })
                        }
                        data-testid={`jobmanager-unarchive-${job.job_id}`}
                        className="shrink-0 rounded p-1 text-text-muted hover:bg-surface-raised hover:text-text"
                        title="Return this job to the job manager"
                      >
                        <Undo2 size={12} />
                      </button>
                    )}
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
      {sharing && (
        <ShareDialog
          kind="job"
          resourceId={sharing.id}
          resourceName={sharing.name}
          open
          onClose={() => setSharing(null)}
        />
      )}
    </>
  );
}

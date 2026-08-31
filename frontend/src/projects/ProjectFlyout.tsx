import { useState } from "react";
import { Undo2, Loader2 } from "lucide-react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Flyout } from "../app-shell/Flyout";
import { DownloadButton } from "../app-shell/DownloadButton";
import { StatusDot } from "../jobs/StatusDot";
import { JobDetailDrawer } from "../jobs/JobDetailDrawer";
import { triggerDownload } from "../lib/download";
import { jobsListQueryKey, projectQueryKey, projectsQueryKey, useProjectQuery } from "../lib/queries";
import * as api from "../lib/api";
import { formatBytes } from "./formatBytes";

/**
 * One project's contents, opened by clicking its row in the left rail.
 *
 * A flyout rather than an inline disclosure inside the rail: the rail is
 * 220-520px wide and this is a table of jobs, which is the same reason the
 * Knowledge base and Files sections put their detail views here. It opens
 * only on an explicit click and never over a preview the user is reading.
 *
 * This is the "back" half of moving jobs between the job manager and the
 * archive. The "forward" half is the Add to project control in
 * JobManagerPanel's selection bar.
 */
export function ProjectFlyout({ projectId, onClose }: { projectId: string; onClose: () => void }) {
  const query = useProjectQuery(projectId);
  const queryClient = useQueryClient();
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [openJobId, setOpenJobId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const project = query.data;

  const removeMutation = useMutation({
    mutationFn: (jobIds: string[]) => api.removeProjectJobs(projectId, jobIds),
    onSuccess: () => {
      setSelected(new Set());
      setError(null);
      queryClient.invalidateQueries({ queryKey: projectQueryKey(projectId) });
      queryClient.invalidateQueries({ queryKey: projectsQueryKey });
      // The job manager list, both the archived and unarchived variants:
      // a returned job leaves one and joins the other, so invalidating by
      // the shared key prefix covers both cache entries at once.
      queryClient.invalidateQueries({ queryKey: jobsListQueryKey });
    },
    onError: (e) => setError(String(e instanceof Error ? e.message : e)),
  });

  const toggle = (jobId: string) =>
    setSelected((s) => {
      const next = new Set(s);
      if (next.has(jobId)) next.delete(jobId);
      else next.add(jobId);
      return next;
    });

  const jobs = project?.jobs ?? [];
  const allSelected = jobs.length > 0 && selected.size === jobs.length;

  return (
    <>
      <Flyout
        open
        onClose={onClose}
        title={project ? project.name : "Project"}
        widthClassName="w-140"
        headerActions={
          project && project.job_count > 0 ? (
            <DownloadButton
              title={`Download "${project.name}" as a zip`}
              testId="project-flyout-download"
              // An empty filename so the browser takes the name from the
              // response's Content-Disposition, which is where the
              // slugified, injection-safe project name comes from. See
              // lib/download.ts.
              onDownload={() => triggerDownload(api.projectDownloadUrl(projectId), "")}
              onError={setError}
            />
          ) : null
        }
      >
        {query.isLoading && <div className="skeleton-shimmer h-20 rounded" />}
        {query.isError && (
          <div data-testid="project-flyout-error" className="text-xs text-status-failed">
            Couldn't load this project: {String(query.error)}
          </div>
        )}
        {project && (
          <div className="flex flex-col gap-2">
            <div className="text-[11px] text-text-muted" data-testid="project-flyout-summary">
              {project.job_count} {project.job_count === 1 ? "job" : "jobs"} &middot;{" "}
              {formatBytes(project.size_bytes)}
            </div>
            {project.description && <div className="text-xs text-text-muted">{project.description}</div>}

            {jobs.length === 0 ? (
              <div data-testid="project-flyout-empty" className="text-xs text-text-muted">
                This project is empty. Select jobs in the job manager and use "Add to project" to file them
                here.
              </div>
            ) : (
              <>
                <div className="flex items-center justify-between border-b border-border pb-1.5">
                  <label className="flex items-center gap-1.5 text-[11px] text-text-muted">
                    <input
                      type="checkbox"
                      checked={allSelected}
                      data-testid="project-flyout-select-all"
                      onChange={() =>
                        setSelected(allSelected ? new Set() : new Set(jobs.map((j) => j.job_id)))
                      }
                    />
                    {selected.size > 0 ? `${selected.size} selected` : "Select all"}
                  </label>
                  <button
                    onClick={() => removeMutation.mutate([...selected])}
                    disabled={selected.size === 0 || removeMutation.isPending}
                    data-testid="project-flyout-return-selected"
                    className="flex items-center gap-1 rounded bg-accent px-2 py-1 text-[11px] text-white disabled:opacity-40"
                  >
                    {removeMutation.isPending ? (
                      <Loader2 size={11} className="animate-spin" />
                    ) : (
                      <Undo2 size={11} />
                    )}
                    Return to job manager
                  </button>
                </div>

                {/* table-fixed for the reason JobManagerPanel and JobsPanel
                    both are: under auto layout a long job label sets the
                    column's minimum width and the table outgrows the
                    flyout, putting the action column behind a scrollbar. */}
                <table className="w-full table-fixed text-xs">
                  <tbody>
                    {jobs.map((job) => (
                      <tr
                        key={job.job_id}
                        data-testid={`project-job-row-${job.job_id}`}
                        onClick={() => setOpenJobId(job.job_id)}
                        className="cursor-pointer border-t border-border hover:bg-surface-raised"
                      >
                        <td className="w-6 py-2" onClick={(e) => e.stopPropagation()}>
                          <input
                            type="checkbox"
                            checked={selected.has(job.job_id)}
                            data-testid={`project-job-check-${job.job_id}`}
                            onChange={() => toggle(job.job_id)}
                          />
                        </td>
                        <td className="w-6 py-2">
                          <StatusDot status={job.status} />
                        </td>
                        <td className="min-w-0 py-2">
                          <div className="fade-edge-right text-text" title={job.label}>
                            {job.label}
                          </div>
                          <div className="fade-edge-right font-mono text-[10.5px] text-text-muted">
                            {job.job_id} &middot; {job.engine}
                          </div>
                        </td>
                        <td className="w-9 py-2 pr-1" onClick={(e) => e.stopPropagation()}>
                          <button
                            onClick={() => removeMutation.mutate([job.job_id])}
                            data-testid={`project-job-return-${job.job_id}`}
                            className="rounded p-1 text-text-muted hover:bg-surface-raised hover:text-text"
                            title="Return this job to the job manager"
                          >
                            <Undo2 size={12} />
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </>
            )}
            {error && (
              <div data-testid="project-flyout-action-error" className="text-[11px] text-status-failed">
                {error}
              </div>
            )}
          </div>
        )}
      </Flyout>
      {openJobId && <JobDetailDrawer jobId={openJobId} onClose={() => setOpenJobId(null)} />}
    </>
  );
}

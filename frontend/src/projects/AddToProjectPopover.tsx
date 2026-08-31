import { useState } from "react";
import { Loader2, Plus } from "lucide-react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { jobsListQueryKey, projectsQueryKey, useProjectsQuery } from "../lib/queries";
import * as api from "../lib/api";

/**
 * The forward half of moving jobs between the job manager and the archive:
 * pick an existing project, or name a new one, for the rows currently
 * selected in JobManagerPanel.
 *
 * Filing a job that already sits in another project MOVES it -- a job
 * belongs to at most one project, enforced server-side in one atomic write
 * (see app/projects/registry.py's add_jobs). The wording here says so
 * rather than leaving someone to discover it.
 */
export function AddToProjectPopover({
  jobIds, onClose, onDone,
}: {
  jobIds: string[];
  onClose: () => void;
  onDone: () => void;
}) {
  const projectsQuery = useProjectsQuery();
  const queryClient = useQueryClient();
  const [newName, setNewName] = useState("");
  const [error, setError] = useState<string | null>(null);

  const settle = () => {
    queryClient.invalidateQueries({ queryKey: projectsQueryKey });
    queryClient.invalidateQueries({ queryKey: jobsListQueryKey });
    onDone();
  };

  const addMutation = useMutation({
    mutationFn: (projectId: string) => api.addProjectJobs(projectId, jobIds),
    onSuccess: settle,
    onError: (e) => setError(String(e instanceof Error ? e.message : e)),
  });

  const createMutation = useMutation({
    mutationFn: (name: string) => api.createProject(name, jobIds),
    onSuccess: settle,
    onError: (e) => setError(String(e instanceof Error ? e.message : e)),
  });

  const pending = addMutation.isPending || createMutation.isPending;
  const projects = projectsQuery.data ?? [];
  const n = jobIds.length;

  return (
    <div
      data-testid="add-to-project-popover"
      className="absolute right-2 top-full z-30 mt-1 w-64 rounded border border-border bg-surface p-2 shadow-xl"
    >
      <div className="mb-1.5 text-[11px] text-text-muted">
        File {n} {n === 1 ? "job" : "jobs"} into a project. {n === 1 ? "It leaves" : "They leave"} this list
        until you send {n === 1 ? "it" : "them"} back.
      </div>

      {projects.length > 0 && (
        <div className="mb-1.5 flex max-h-40 flex-col overflow-y-auto">
          {projects.map((p) => (
            <button
              key={p.project_id}
              onClick={() => addMutation.mutate(p.project_id)}
              disabled={pending}
              data-testid={`add-to-project-${p.project_id}`}
              className="flex items-center justify-between gap-2 rounded px-1.5 py-1 text-left text-xs text-text hover:bg-surface-raised disabled:opacity-40"
            >
              <span className="fade-edge-right min-w-0 flex-1">{p.name}</span>
              <span className="shrink-0 text-[10px] tabular-nums text-text-muted">{p.job_count}</span>
            </button>
          ))}
        </div>
      )}

      <div className="flex items-center gap-1 border-t border-border pt-1.5">
        <input
          autoFocus
          value={newName}
          onChange={(e) => setNewName(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && newName.trim()) createMutation.mutate(newName.trim());
            if (e.key === "Escape") onClose();
          }}
          placeholder="New project..."
          aria-label="New project name"
          data-testid="add-to-project-new-name"
          className="min-w-0 flex-1 rounded border border-border bg-surface px-1.5 py-1 text-xs text-text outline-none placeholder:text-text-muted focus:border-accent"
        />
        <button
          onClick={() => newName.trim() && createMutation.mutate(newName.trim())}
          disabled={!newName.trim() || pending}
          data-testid="add-to-project-create"
          className="shrink-0 rounded bg-accent p-1 text-white disabled:opacity-40"
          title="Create this project and file the selected jobs into it"
        >
          {pending ? <Loader2 size={12} className="animate-spin" /> : <Plus size={12} />}
        </button>
      </div>

      {error && (
        <div data-testid="add-to-project-error" className="mt-1 text-[11px] text-status-failed">
          {error}
        </div>
      )}
      <button
        onClick={onClose}
        data-testid="add-to-project-cancel"
        className="mt-1 w-full rounded px-1.5 py-0.5 text-[11px] text-text-muted hover:text-text"
      >
        Cancel
      </button>
    </div>
  );
}

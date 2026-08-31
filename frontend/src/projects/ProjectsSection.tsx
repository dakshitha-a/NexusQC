import { useMemo, useState } from "react";
import { Archive, Loader2, Pencil, Plus, Search, Trash2, X } from "lucide-react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { CollapsibleSection } from "../app-shell/CollapsibleSection";
import { DownloadButton } from "../app-shell/DownloadButton";
import { ProjectDeleteDialog } from "./ProjectDeleteDialog";
import { ProjectFlyout } from "./ProjectFlyout";
import { formatBytes } from "./formatBytes";
import { triggerDownload } from "../lib/download";
import { fuzzyRecordScore } from "../lib/fuzzy";
import { jobsListQueryKey, projectsQueryKey, useProjectsQuery } from "../lib/queries";
import * as api from "../lib/api";
import type { ProjectRow } from "../lib/api";

/**
 * Project archives in the left rail, beside Conversations, Knowledge base
 * and Files.
 *
 * A project is a named bundle of finished jobs. Filing jobs into one takes
 * them off the job manager's list, which is the point: that list otherwise
 * only ever grows, and a study that took thirty calculations sits on top of
 * the next study's forever.
 *
 * Nothing here moves a file. Archiving is a membership label and the job
 * directories stay exactly where quota accounting, the conversation
 * registry and every download route already look for them -- see
 * app/projects/registry.py for why that constraint is not negotiable.
 */
function NewProjectForm({ onDone }: { onDone: () => void }) {
  const queryClient = useQueryClient();
  const [name, setName] = useState("");

  const createMutation = useMutation({
    mutationFn: (n: string) => api.createProject(n),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: projectsQueryKey });
      onDone();
    },
  });

  return (
    <div className="flex flex-col gap-2 rounded border border-border bg-surface-raised p-2">
      <input
        autoFocus
        value={name}
        onChange={(e) => setName(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && name.trim()) createMutation.mutate(name.trim());
          if (e.key === "Escape") onDone();
        }}
        placeholder="Project name"
        aria-label="New project name"
        data-testid="project-new-name"
        className="w-full rounded border border-border bg-surface px-2 py-1 text-xs text-text outline-none placeholder:text-text-muted focus:border-accent"
      />
      <div className="flex gap-2">
        <button
          onClick={() => name.trim() && createMutation.mutate(name.trim())}
          disabled={!name.trim() || createMutation.isPending}
          data-testid="project-new-create"
          className="rounded bg-accent px-2 py-1 text-xs text-white disabled:opacity-40"
        >
          {createMutation.isPending ? "Creating..." : "Create"}
        </button>
        <button onClick={onDone} className="rounded px-2 py-1 text-xs text-text-muted hover:text-text">
          Cancel
        </button>
      </div>
      {createMutation.isError && (
        <div data-testid="project-new-error" className="text-xs text-status-failed">
          {String(createMutation.error)}
        </div>
      )}
    </div>
  );
}

export function ProjectsSection() {
  const projectsQuery = useProjectsQuery();
  const queryClient = useQueryClient();
  // Collapsed to start, matching the Knowledge base and Files sections
  // either side of it. Conversations is the one section that is always
  // open, because it is what the sidebar is primarily for; three expanded
  // sections below it would push the conversation list off the screen.
  // The subHeader stays visible while collapsed, so an archive still
  // announces itself by its project and job counts.
  const [collapsed, setCollapsed] = useState(true);
  const [adding, setAdding] = useState(false);
  const [search, setSearch] = useState("");
  const [openProjectId, setOpenProjectId] = useState<string | null>(null);
  const [renamingId, setRenamingId] = useState<string | null>(null);
  const [renameValue, setRenameValue] = useState("");
  const [deleting, setDeleting] = useState<ProjectRow | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [downloadError, setDownloadError] = useState<string | null>(null);

  const projects = projectsQuery.data ?? [];

  const renameMutation = useMutation({
    mutationFn: ({ id, name }: { id: string; name: string }) => api.updateProject(id, { name }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: projectsQueryKey });
      // A rename changes the badge every archived job row shows, so the
      // job manager's archived view is stale until this lands too.
      queryClient.invalidateQueries({ queryKey: jobsListQueryKey });
    },
  });

  const deleteMutation = useMutation({
    mutationFn: ({ id, deleteJobs }: { id: string; deleteJobs: boolean }) => api.deleteProject(id, deleteJobs),
    onSuccess: () => {
      setDeleting(null);
      setDeleteError(null);
      queryClient.invalidateQueries({ queryKey: projectsQueryKey });
      queryClient.invalidateQueries({ queryKey: jobsListQueryKey });
    },
    onError: (e) => setDeleteError(String(e instanceof Error ? e.message : e)),
  });

  // Same fuzzy matcher the job manager's search uses, so "urcphot" finds
  // "Uracil photochemistry" here exactly as it would find a job there.
  const filtered = useMemo(() => {
    if (!search.trim()) return projects;
    const scored: { project: ProjectRow; score: number }[] = [];
    for (const project of projects) {
      const score = fuzzyRecordScore(
        [
          { text: project.name, weight: 1 },
          { text: project.description, weight: 0.6 },
        ],
        search,
      );
      if (score !== null) scored.push({ project, score });
    }
    scored.sort((a, b) => b.score - a.score);
    return scored.map((s) => s.project);
  }, [projects, search]);

  const totalJobs = projects.reduce((n, p) => n + p.job_count, 0);
  const totalBytes = projects.reduce((n, p) => n + p.size_bytes, 0);

  return (
    <>
      <CollapsibleSection
        title="Projects"
        collapsed={collapsed}
        onToggle={() => setCollapsed((c) => !c)}
        headerExtra={
          <button
            onClick={(e) => {
              e.stopPropagation();
              setAdding((a) => !a);
            }}
            data-testid="project-add-toggle"
            className="rounded p-0.5 text-text-muted hover:bg-surface-raised hover:text-text"
            title="New project"
          >
            {adding ? <X size={13} /> : <Plus size={13} />}
          </button>
        }
        subHeader={
          projects.length > 0 ? (
            <div className="text-[10px] tabular-nums text-text-muted" data-testid="projects-total">
              {projects.length} {projects.length === 1 ? "project" : "projects"} &middot; {totalJobs}{" "}
              {totalJobs === 1 ? "job" : "jobs"} &middot; {formatBytes(totalBytes)}
            </div>
          ) : null
        }
      >
        <div className="flex flex-col gap-1.5 px-3 pb-2">
          {adding && <NewProjectForm onDone={() => setAdding(false)} />}

          {projectsQuery.isLoading && <div className="skeleton-shimmer h-8 rounded" />}
          {projectsQuery.isError && (
            <div data-testid="projects-error" className="text-[11px] text-status-failed">
              Couldn't load projects: {String(projectsQuery.error)}
            </div>
          )}

          {!projectsQuery.isLoading && projects.length === 0 && (
            <div
              data-testid="projects-empty"
              className="flex items-start gap-1.5 rounded border border-dashed border-border px-2 py-1.5 text-[11px] text-text-muted"
            >
              <Archive size={12} className="mt-0.5 shrink-0" />
              Select finished jobs in the job manager and use "Add to project" to bundle them here.
            </div>
          )}

          {projects.length > 0 && (
            <div className="flex items-center gap-1.5 rounded border border-border bg-surface-raised px-2 py-1">
              <Search size={12} className="text-text-muted" />
              <input
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Escape") setSearch("");
                }}
                placeholder="Search projects..."
                aria-label="Search projects"
                data-testid="projects-search"
                className="min-w-0 flex-1 bg-transparent text-xs text-text placeholder:text-text-muted outline-none"
              />
            </div>
          )}

          {downloadError && <div className="text-[11px] text-status-failed">{downloadError}</div>}

          {search.trim() && filtered.length === 0 && (
            <div data-testid="projects-search-empty" className="text-[11px] text-text-muted">
              No projects match that search.
            </div>
          )}

          <div className="flex flex-col">
            {filtered.map((project) => (
              <div
                key={project.project_id}
                data-testid={`project-row-${project.project_id}`}
                className="group flex items-center gap-1 py-0.5 text-xs"
              >
                {renamingId === project.project_id ? (
                  <input
                    autoFocus
                    value={renameValue}
                    onChange={(e) => setRenameValue(e.target.value)}
                    onBlur={() => {
                      if (renameValue.trim()) {
                        renameMutation.mutate({ id: project.project_id, name: renameValue.trim() });
                      }
                      setRenamingId(null);
                    }}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") e.currentTarget.blur();
                      if (e.key === "Escape") setRenamingId(null);
                    }}
                    data-testid={`project-rename-input-${project.project_id}`}
                    className="min-w-0 flex-1 rounded border border-border bg-surface px-1 py-0.5 text-xs text-text outline-none"
                  />
                ) : (
                  <button
                    onClick={() => setOpenProjectId(project.project_id)}
                    data-testid={`project-open-${project.project_id}`}
                    className="min-w-0 flex-1 text-left"
                    title={project.description || project.name}
                  >
                    <div className="fade-edge-right text-text hover:underline">{project.name}</div>
                    <div className="text-[10.5px] tabular-nums text-text-muted">
                      {project.job_count} {project.job_count === 1 ? "job" : "jobs"} &middot;{" "}
                      {formatBytes(project.size_bytes)}
                    </div>
                  </button>
                )}

                {/* Held open by group-hover rather than always visible, the
                    same way the Files rows' actions are -- three controls
                    per row at a 220px rail would leave no room for a name. */}
                <div className="flex shrink-0 items-center opacity-0 group-hover:opacity-100 focus-within:opacity-100">
                  <button
                    onClick={() => {
                      setRenamingId(project.project_id);
                      setRenameValue(project.name);
                    }}
                    data-testid={`project-rename-${project.project_id}`}
                    className="rounded p-1 text-text-muted hover:bg-surface-raised hover:text-text"
                    title="Rename project"
                  >
                    <Pencil size={11} />
                  </button>
                  <DownloadButton
                    title={`Download "${project.name}" as a zip`}
                    testId={`project-download-${project.project_id}`}
                    size={11}
                    className="p-1"
                    disabled={project.job_count === 0}
                    onDownload={() => triggerDownload(api.projectDownloadUrl(project.project_id), "")}
                    onError={setDownloadError}
                  />
                  <button
                    onClick={() => {
                      setDeleting(project);
                      setDeleteError(null);
                    }}
                    data-testid={`project-delete-${project.project_id}`}
                    className="rounded p-1 text-text-muted hover:bg-surface-raised hover:text-status-failed"
                    title="Delete project"
                  >
                    {deleteMutation.isPending && deleteMutation.variables?.id === project.project_id ? (
                      <Loader2 size={11} className="animate-spin" />
                    ) : (
                      <Trash2 size={11} />
                    )}
                  </button>
                </div>
              </div>
            ))}
          </div>
        </div>
      </CollapsibleSection>

      {openProjectId && (
        <ProjectFlyout projectId={openProjectId} onClose={() => setOpenProjectId(null)} />
      )}
      {deleting && (
        <ProjectDeleteDialog
          project={deleting}
          open
          onClose={() => setDeleting(null)}
          onConfirm={(deleteJobs) => deleteMutation.mutate({ id: deleting.project_id, deleteJobs })}
          pending={deleteMutation.isPending}
          error={deleteError}
        />
      )}
    </>
  );
}

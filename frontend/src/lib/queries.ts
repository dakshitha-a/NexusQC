// Centralized TanStack Query hooks + query keys, so invalidation calls
// elsewhere (server/routes push events handled in lib/sse.ts) target the
// exact same keys these hooks read.
import { useQuery } from "@tanstack/react-query";
import * as api from "./api";
import { useChatStore } from "./chatStore";
import type { JobRow } from "./api";

export const threadsQueryKey = ["threads"] as const;
export const jobsQueryKey = (threadId: string) => ["jobs", threadId] as const;
export const jobsListQueryKey = ["jobs-list"] as const;
export const jobQueryKey = (jobId: string) => ["job", jobId] as const;
export const kbSourcesQueryKey = ["kb-sources"] as const;
export const jobsQuotaQueryKey = ["jobs-quota"] as const;
export const kbQuotaQueryKey = ["kb-quota"] as const;
export const uploadsQueryKey = ["uploads"] as const;
export const plotsQueryKey = ["plots"] as const;
export const plotQueryKey = (plotId: string) => ["plot", plotId] as const;
export const uploadsQuotaQueryKey = ["uploads-quota"] as const;
export const projectsQueryKey = ["projects"] as const;
export const projectQueryKey = (projectId: string) => ["project", projectId] as const;
export const shareInboxQueryKey = ["share-inbox"] as const;
export const shareOutboxQueryKey = ["share-outbox"] as const;

const TERMINAL_JOB_STATUSES = new Set(["completed", "failed", "cancelled"]);
const isNonTerminal = (status: string | undefined) => !!status && !TERMINAL_JOB_STATUSES.has(status);

export const useThreadsQuery = () => useQuery({ queryKey: threadsQueryKey, queryFn: api.listThreads });

export const useJobsQuery = (threadId: string | null) => {
  // Normally kept fresh by sse.ts invalidating this key on job_update/
  // turn_complete; if the SSE connection is down, fall back to polling
  // so the jobs list doesn't sit silently stale for the rest of an outage
  // (there was previously no fallback at all here).
  const sseConnected = useChatStore((s) => s.sseConnected);
  return useQuery({
    queryKey: jobsQueryKey(threadId ?? ""),
    queryFn: () => api.listJobs(threadId as string),
    enabled: !!threadId,
    refetchInterval: (query) => {
      if (sseConnected) return false;
      const jobs = query.state.data as JobRow[] | undefined;
      return jobs?.some((j) => isNonTerminal(j.status)) ? 4000 : false;
    },
  });
};

// The Job Manager panel is global/cross-thread, so there's no per-thread SSE
// stream to invalidate it on a job_update event (see lib/sse.ts) -- polled
// on a plain interval instead, same low-stakes reasoning as LiveLogPanel's
// polling (a job list is cheap to refetch and not app-critical state).
// includeArchived is part of the key, not just the fetcher: the two lists
// are genuinely different sets of rows, so sharing one cache entry would
// show the wrong one for a tick every time the toggle moves.
export const useJobsListQuery = (includeArchived = false) =>
  useQuery({
    queryKey: [...jobsListQueryKey, includeArchived] as const,
    queryFn: () => api.listAllJobs(includeArchived),
    refetchInterval: 4000,
  });

// Polled like the job list, and for the same reason: a project's job count
// and archive size change whenever a job is filed, returned or evicted, and
// there is no per-thread SSE stream that would know about any of it.
export const useProjectsQuery = () =>
  useQuery({ queryKey: projectsQueryKey, queryFn: api.listProjects, refetchInterval: 8000 });

export const useProjectQuery = (projectId: string | null) =>
  useQuery({
    queryKey: projectQueryKey(projectId ?? ""),
    queryFn: () => api.getProject(projectId as string),
    enabled: !!projectId,
  });

// Disk usage only grows on job submission/KB ingestion (see
// app/chemistry/jobs/quota.py, app/rag/quota.py) -- a much slower-moving
// number than the job list itself, so a longer interval is enough to keep
// the panel headers honest without adding real polling load.
export const useJobsQuotaQuery = () =>
  useQuery({ queryKey: jobsQuotaQueryKey, queryFn: api.getJobsQuota, refetchInterval: 30000 });

export const useJobQuery = (jobId: string | null) => {
  // Same SSE-drop fallback as useJobsQuery above -- normally sse.ts
  // invalidates ["job", jobId] on that job's own job_update event, so an
  // open JobDetailDrawer doesn't need to poll at all while connected.
  // "Is a stream open?" was the wrong question, and R-027 is the answer to
  // the right one. There is one SSE stream, for the ACTIVE conversation, and
  // job_update events reach it only for jobs belonging to that conversation
  // (the watcher publishes per thread). The Job Manager panel is
  // cross-conversation by design, so opening a running job from another
  // conversation -- or one submitted outside any conversation -- gave a
  // drawer that was told not to poll because a stream was connected, and
  // that stream would never carry this job's updates. The header said
  // "running" for ever, no summary or artifacts ever arrived, and the row
  // behind it turned green on its own 4 s poll.
  //
  // So the poll is suppressed only when the open job belongs to the
  // conversation whose stream is actually connected.
  const sseConnected = useChatStore((s) => s.sseConnected);
  const activeThreadId = useChatStore((s) => s.threadId);
  return useQuery({
    queryKey: jobQueryKey(jobId ?? ""),
    queryFn: () => api.getJob(jobId as string),
    enabled: !!jobId,
    refetchInterval: (query) => {
      const job = query.state.data as JobRow | undefined;
      const coveredByStream =
        sseConnected && !!activeThreadId && !!job?.thread_id && job.thread_id === activeThreadId;
      if (coveredByStream) return false;
      return isNonTerminal(job?.status) ? 4000 : false;
    },
  });
};

// A pes_scan/interp_pes/batch master's per-image (or per-child) sub-jobs --
// polled while the master is still going (each child transitions
// independently), same "not app-critical, a cheap disk read either way"
// reasoning as useJobsListQuery. P7.3: windowed rather than all-at-once --
// offset/limit are part of the key so each open window caches separately
// and a page change doesn't refetch the whole master's children.
export const jobChildrenQueryKey = (jobId: string, offset: number, limit: number) =>
  ["job-children", jobId, offset, limit] as const;

export const CHILD_PAGE_SIZE = 100;

/** `isMaster`: true for any master job type (pes_1d/interp_pes OR
 * wigner_ensemble) whose sub-jobs the caller wants to fetch; the backing
 * GET /api/jobs/{id}/children route accepts either. Returns one page
 * (`items`) plus the master's total child count, so the caller (the
 * drawer's flat button list, or a frame viewer reacting to FrameScrubber
 * navigation) can request a different window via `offset` without
 * fetching -- or the backend rendering -- every other child. */
export const useJobChildrenQuery = (
  jobId: string | null, isMaster: boolean, running: boolean, offset: number, limit: number = CHILD_PAGE_SIZE,
) =>
  useQuery({
    queryKey: jobChildrenQueryKey(jobId ?? "", offset, limit),
    queryFn: () => api.getJobChildren(jobId as string, offset, limit),
    enabled: !!jobId && isMaster,
    refetchInterval: running ? 3000 : false,
  });

// A wigner_spectra master's pooled transitions (P8.3's live broadening
// slider) -- fetched once per job id, then re-broadened client-side on
// every slider move with NO further request. `staleTime: Infinity` +
// `refetchOnWindowFocus: false` matter here specifically: TanStack Query's
// own default refetch-on-focus would otherwise fire a real request that a
// "no network on slider move" test could misattribute to the slider
// itself (a focus event during interaction, not the move). Still polls
// while the ensemble is running (same running-aware shape as
// useJobChildrenQuery), since new samples keep completing until then.
export const wignerTransitionsQueryKey = (jobId: string) => ["wigner-transitions", jobId] as const;

export const useWignerTransitionsQuery = (jobId: string | null, isWignerMaster: boolean, running: boolean) =>
  useQuery({
    queryKey: wignerTransitionsQueryKey(jobId ?? ""),
    queryFn: () => api.getWignerTransitions(jobId as string),
    enabled: !!jobId && isWignerMaster,
    refetchInterval: running ? 3000 : false,
    staleTime: running ? 0 : Infinity,
    refetchOnWindowFocus: false,
  });

export const useKbSourcesQuery = () => useQuery({ queryKey: kbSourcesQueryKey, queryFn: api.getKbSources });

// Same "grows slowly, cheap to over-poll" reasoning as useJobsQuotaQuery --
// KB storage only changes when a source is added/removed through this app.
export const useKbQuotaQuery = () =>
  useQuery({ queryKey: kbQuotaQueryKey, queryFn: api.getKbQuota, refetchInterval: 30000 });

export const useUploadsQuery = () => useQuery({ queryKey: uploadsQueryKey, queryFn: api.getUploads });

// Polled rather than SSE-driven: no event announces "a plot was drawn". The
// closest signal is turn_complete, which sse.ts invalidates this key on, so
// the poll is only the backstop for a plot registered outside a turn (a job
// finishing on its own registers its spectra from the watcher loop).
export const usePlotsQuery = () =>
  useQuery({ queryKey: plotsQueryKey, queryFn: api.getPlots, refetchInterval: 8000 });

// Only fetched while a plot's flyout is open: the detail payload carries the
// numbers the plot drew, which the list deliberately omits.
export const usePlotQuery = (plotId: string | null) =>
  useQuery({
    queryKey: plotQueryKey(plotId ?? ""),
    queryFn: () => api.getPlot(plotId as string),
    enabled: !!plotId,
  });

export const useUploadsQuotaQuery = () =>
  useQuery({ queryKey: uploadsQuotaQueryKey, queryFn: api.getUploadsQuota, refetchInterval: 30000 });


// Polled (not SSE-pushed, unlike job status -- see get_job_log's docstring
// in server/routes/jobs.py) only while the job is actually running; the
// caller passes `running` so this stops the instant the job finishes.
export const jobLogQueryKey = (jobId: string) => ["job-log", jobId] as const;

export const useJobLogQuery = (jobId: string | null, running: boolean) =>
  useQuery({
    queryKey: jobLogQueryKey(jobId ?? ""),
    queryFn: () => api.getJobLog(jobId as string, 20),
    enabled: !!jobId && running,
    refetchInterval: running ? 1500 : false,
  });

// Polled at the same 8s cadence as the projects rail, and for the same
// reason: this is list-shaped state the left rail renders, and there is no
// SSE event behind it -- an offer arrives from another user's session
// entirely, which this one never hears about.
//
// `enabled` is the important part. The sharing router is only mounted when
// auth is configured (server/main.py), so on a single-user local
// deployment every one of these calls would 404 forever. Gating on a
// logged-in user keeps the rail section absent rather than permanently
// errored.
export const useShareInboxQuery = (enabled = true) =>
  useQuery({
    queryKey: shareInboxQueryKey,
    queryFn: api.listShareInbox,
    refetchInterval: 8000,
    enabled,
  });

export const useShareOutboxQuery = (enabled = true) =>
  useQuery({
    queryKey: shareOutboxQueryKey,
    queryFn: api.listShareOutbox,
    refetchInterval: 8000,
    enabled,
  });

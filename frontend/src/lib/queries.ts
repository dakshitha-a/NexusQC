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
export const uploadsQuotaQueryKey = ["uploads-quota"] as const;

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
export const useJobsListQuery = () =>
  useQuery({ queryKey: jobsListQueryKey, queryFn: api.listAllJobs, refetchInterval: 4000 });

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
  const sseConnected = useChatStore((s) => s.sseConnected);
  return useQuery({
    queryKey: jobQueryKey(jobId ?? ""),
    queryFn: () => api.getJob(jobId as string),
    enabled: !!jobId,
    refetchInterval: (query) => {
      if (sseConnected) return false;
      return isNonTerminal((query.state.data as JobRow | undefined)?.status) ? 4000 : false;
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

export const useKbSourcesQuery = () => useQuery({ queryKey: kbSourcesQueryKey, queryFn: api.getKbSources });

// Same "grows slowly, cheap to over-poll" reasoning as useJobsQuotaQuery --
// KB storage only changes when a source is added/removed through this app.
export const useKbQuotaQuery = () =>
  useQuery({ queryKey: kbQuotaQueryKey, queryFn: api.getKbQuota, refetchInterval: 30000 });

export const useUploadsQuery = () => useQuery({ queryKey: uploadsQueryKey, queryFn: api.getUploads });

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

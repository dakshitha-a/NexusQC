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
export const jobRegistryQueryKey = ["job-registry"] as const;
export const jobsQuotaQueryKey = ["jobs-quota"] as const;
export const kbQuotaQueryKey = ["kb-quota"] as const;

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

// A pes_scan master's per-image sub-jobs -- polled while the scan is
// still going (each image transitions independently), same "not app-
// critical, a cheap disk read either way" reasoning as useJobsListQuery.
export const jobChildrenQueryKey = (jobId: string) => ["job-children", jobId] as const;

/** `isMaster`: true for any master job type (pes_scan OR wigner_ensemble
 * -- see MASTER_METHODS in app/chemistry/jobs/base.py) whose sub-jobs the
 * caller wants to fetch; the backing GET /api/jobs/{id}/children route
 * accepts either. */
export const useJobChildrenQuery = (jobId: string | null, isMaster: boolean, running: boolean) =>
  useQuery({
    queryKey: jobChildrenQueryKey(jobId ?? ""),
    queryFn: () => api.getJobChildren(jobId as string),
    enabled: !!jobId && isMaster,
    refetchInterval: running ? 3000 : false,
  });

export const useKbSourcesQuery = () => useQuery({ queryKey: kbSourcesQueryKey, queryFn: api.getKbSources });

// Same "grows slowly, cheap to over-poll" reasoning as useJobsQuotaQuery --
// KB storage only changes when a source is added/removed through this app.
export const useKbQuotaQuery = () =>
  useQuery({ queryKey: kbQuotaQueryKey, queryFn: api.getKbQuota, refetchInterval: 30000 });

export const useJobRegistryQuery = () =>
  useQuery({ queryKey: jobRegistryQueryKey, queryFn: api.getJobRegistry, staleTime: Infinity });

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

// Centralized TanStack Query hooks + query keys, so invalidation calls
// elsewhere (server/routes push events handled in lib/sse.ts) target the
// exact same keys these hooks read.
import { useQuery } from "@tanstack/react-query";
import * as api from "./api";

export const threadsQueryKey = ["threads"] as const;
export const jobsQueryKey = (threadId: string) => ["jobs", threadId] as const;
export const jobsListQueryKey = ["jobs-list"] as const;
export const jobQueryKey = (jobId: string) => ["job", jobId] as const;
export const kbSourcesQueryKey = ["kb-sources"] as const;
export const toolsQueryKey = ["tools"] as const;
export const jobRegistryQueryKey = ["job-registry"] as const;

export const useThreadsQuery = () => useQuery({ queryKey: threadsQueryKey, queryFn: api.listThreads });

export const useJobsQuery = (threadId: string | null) =>
  useQuery({
    queryKey: jobsQueryKey(threadId ?? ""),
    queryFn: () => api.listJobs(threadId as string),
    enabled: !!threadId,
  });

// The Job Manager panel is global/cross-thread, so there's no per-thread SSE
// stream to invalidate it on a job_update event (see lib/sse.ts) -- polled
// on a plain interval instead, same low-stakes reasoning as LiveLogPanel's
// polling (a job list is cheap to refetch and not app-critical state).
export const useJobsListQuery = () =>
  useQuery({ queryKey: jobsListQueryKey, queryFn: api.listAllJobs, refetchInterval: 4000 });

export const useJobQuery = (jobId: string | null) =>
  useQuery({
    queryKey: jobQueryKey(jobId ?? ""),
    queryFn: () => api.getJob(jobId as string),
    enabled: !!jobId,
  });

export const useKbSourcesQuery = () => useQuery({ queryKey: kbSourcesQueryKey, queryFn: api.getKbSources });

export const useToolsQuery = () => useQuery({ queryKey: toolsQueryKey, queryFn: api.listTools });

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

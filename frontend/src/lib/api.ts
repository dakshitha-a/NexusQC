// Thin fetch wrappers over server/'s REST endpoints. Relative paths (e.g.
// "/api/threads") are proxied to the FastAPI backend by Vite's dev server
// (see vite.config.ts) so no base URL/CORS handling is needed here.

export interface ThreadSummary {
  thread_id: string;
  label: string;
  created_at: number;
  last_active_at: number;
  active_job_ids: string[];
}

export interface ChatMessage {
  id: string | null;
  type: "HumanMessage" | "AIMessage" | "ToolMessage" | "SystemMessage";
  content: string;
  name: string | null;
  tool_call_id: string | null;
  tool_calls: { name: string; args: Record<string, unknown>; id: string }[];
}

export interface PendingApproval {
  kind: "job_approval" | "tool_approval";
  [key: string]: unknown;
}

export interface MoleculeDict {
  name?: string;
  smiles?: string;
  charge?: number;
  multiplicity?: number;
  symbols: string[];
  coords: [number, number, number][];
  [key: string]: unknown;
}

export interface ThreadState {
  messages: ChatMessage[];
  molecule: MoleculeDict | null;
  active_job_ids: string[];
  dynamic_tool_artifacts: string[];
  pending_approval: PendingApproval | null;
}

export interface JobRow {
  job_id: string;
  status: "pending" | "running" | "completed" | "failed" | "cancelled";
  message: string;
  updated_at: number | null;
  method: string | null;
  engine: string | null;
  label: string;
  params: Record<string, unknown>;
  retried_from: string | null;
  retry_count: number;
  summary: Record<string, unknown> | null;
  // Most artifacts are a single file path (e.g. uvvis_spectrum); "cubes" is
  // a nested dict of orbital-label -> file path (see MoCubeViewer).
  artifacts: Record<string, string | Record<string, string>> | null;
  error: string | null;
}

export interface KbSource {
  source: string;
  doc_type: "manual" | "paper";
  n_chunks: number;
}

export interface DynamicTool {
  name: string;
  description: string;
  param_description: string;
  created_at: string;
}

export interface JobRegistry {
  methods: string[];
  default_engine: Record<string, string>;
  allowed_engines: Record<string, string[]>;
  required_params: Record<string, string[]>;
  optional_params: Record<string, Record<string, unknown>>;
  param_help: Record<string, string>;
}

class ApiError extends Error {
  status: number;
  constructor(status: number, detail: string) {
    super(detail);
    this.status = status;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    ...init,
    headers: init?.body instanceof FormData ? init.headers : { "Content-Type": "application/json", ...init?.headers },
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail ?? detail;
    } catch {
      /* body wasn't JSON -- fall back to statusText */
    }
    throw new ApiError(res.status, detail);
  }
  if (res.status === 204) return undefined as T;
  return res.json();
}

// --- Threads -----------------------------------------------------------
export const listThreads = () => request<ThreadSummary[]>("/api/threads");
export const createThread = (label?: string) =>
  request<ThreadSummary>("/api/threads", { method: "POST", body: JSON.stringify({ label }) });
export const renameThread = (threadId: string, label: string) =>
  request<ThreadSummary>(`/api/threads/${threadId}`, { method: "PATCH", body: JSON.stringify({ label }) });
export const deleteThread = (threadId: string) =>
  request<{ deleted: boolean }>(`/api/threads/${threadId}`, { method: "DELETE" });

// --- Chat ----------------------------------------------------------------
export const getThreadState = (threadId: string) => request<ThreadState>(`/api/threads/${threadId}/state`);
export const postMessage = (threadId: string, text: string) =>
  request<{ accepted: boolean }>(`/api/threads/${threadId}/messages`, {
    method: "POST",
    body: JSON.stringify({ text }),
  });
export const approveJob = (threadId: string, approved: boolean, inputText?: string | null) =>
  request<{ resumed: boolean }>(`/api/threads/${threadId}/approvals/job`, {
    method: "POST",
    body: JSON.stringify({ approved, input_text: inputText ?? null }),
  });
export const approveTool = (threadId: string, approved: boolean, code?: string | null) =>
  request<{ resumed: boolean }>(`/api/threads/${threadId}/approvals/tool`, {
    method: "POST",
    body: JSON.stringify({ approved, code: code ?? null }),
  });

// --- Jobs ------------------------------------------------------------------
export const listJobs = (threadId: string) => request<JobRow[]>(`/api/threads/${threadId}/jobs`);
export const getJob = (jobId: string) => request<JobRow>(`/api/jobs/${jobId}`);
export const cancelJob = (jobId: string) =>
  request<{ cancelled: boolean } & JobRow>(`/api/jobs/${jobId}/cancel`, { method: "POST" });
export const jobArtifactUrl = (jobId: string, key: string) => `/api/jobs/${jobId}/artifacts/${key}`;

// --- Job registry ------------------------------------------------------
export const getJobRegistry = () => request<JobRegistry>("/api/job-registry");

// --- Knowledge base ------------------------------------------------------
export const getKbSources = () => request<KbSource[]>("/api/kb/sources");
export const addKbSource = (file: File, docType: "manual" | "paper") => {
  const form = new FormData();
  form.append("file", file);
  form.append("doc_type", docType);
  return request<KbSource>("/api/kb/sources", { method: "POST", body: form });
};
export const deleteKbSource = (source: string) =>
  request<{ deleted_chunks: number }>(`/api/kb/sources/${encodeURIComponent(source)}`, { method: "DELETE" });

// --- Dynamic tools -----------------------------------------------------
export const listTools = () => request<DynamicTool[]>("/api/tools");
export const deleteTool = (name: string) =>
  request<{ deleted: boolean }>(`/api/tools/${encodeURIComponent(name)}`, { method: "DELETE" });

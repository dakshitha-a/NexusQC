// Thin fetch wrappers over server/'s REST endpoints. Relative paths (e.g.
// "/api/threads") are proxied to the FastAPI backend by Vite's dev server
// (see vite.config.ts) so no base URL/CORS handling is needed here.

export interface ThreadSummary {
  thread_id: string;
  label: string;
  created_at: number;
  last_active_at: number;
  active_job_ids: string[];
  pinned: boolean;
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
  created_at: number | null;
  method: string | null;
  engine: string | null;
  label: string;
  params: Record<string, unknown>;
  retried_from: string | null;
  retry_count: number;
  // True for a pes_scan "master" job -- see server/routes/jobs.py's
  // is_scan_master. Its own per-image sub-jobs (parent_job_id set) never
  // appear in any job list, only via getJobChildren below.
  is_scan_master: boolean;
  parent_job_id: string | null;
  // Omitted by the list endpoints (listJobs/listAllJobs) -- only the
  // single-job GET (getJob, used by JobDetailDrawer) includes these.
  summary?: Record<string, unknown> | null;
  molecule?: MoleculeDict | null;
  // Most artifacts are a single file path (e.g. uvvis_spectrum); "cubes" is
  // a nested dict of orbital-label -> file path (see MoCubeViewer).
  artifacts?: Record<string, string | Record<string, string>> | null;
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
export const setThreadPinned = (threadId: string, pinned: boolean) =>
  request<ThreadSummary>(`/api/threads/${threadId}/pin`, { method: "PATCH", body: JSON.stringify({ pinned }) });

// --- Chat ----------------------------------------------------------------
export const getThreadState = (threadId: string) => request<ThreadState>(`/api/threads/${threadId}/state`);
export const postMessage = (threadId: string, text: string, jobIds: string[] = []) =>
  request<{ accepted: boolean }>(`/api/threads/${threadId}/messages`, {
    method: "POST",
    body: JSON.stringify({ text, job_ids: jobIds }),
  });
export const stopTurn = (threadId: string) =>
  request<{ accepted: boolean }>(`/api/threads/${threadId}/stop`, { method: "POST" });
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
export const resetMolecule = (threadId: string) =>
  request<ThreadState>(`/api/threads/${threadId}/molecule/reset`, { method: "POST" });

// --- Jobs ------------------------------------------------------------------
export const listJobs = (threadId: string) => request<JobRow[]>(`/api/threads/${threadId}/jobs`);
// Global, cross-thread job list -- backs the persistent Job Manager panel,
// distinct from listJobs() above (one conversation's active_job_ids only).
export const listAllJobs = () => request<JobRow[]>("/api/jobs");
export const getJob = (jobId: string) => request<JobRow>(`/api/jobs/${jobId}`);
export const renameJob = (jobId: string, label: string) =>
  request<JobRow>(`/api/jobs/${jobId}`, { method: "PATCH", body: JSON.stringify({ label }) });
export const deleteJob = (jobId: string) => request<{ deleted: boolean }>(`/api/jobs/${jobId}`, { method: "DELETE" });
export const cancelJob = (jobId: string) =>
  request<{ cancelled: boolean } & JobRow>(`/api/jobs/${jobId}/cancel`, { method: "POST" });
export const jobArtifactUrl = (jobId: string, key: string) => `/api/jobs/${jobId}/artifacts/${key}`;
export const orbitalCubeUrl = (jobId: string, index: number, spin?: string | null) =>
  `/api/jobs/${jobId}/orbitals/${index}/cube${spin ? `?spin=${spin}` : ""}`;
export const getJobLog = (jobId: string, lines = 20) =>
  request<{ lines: string[] }>(`/api/jobs/${jobId}/log?lines=${lines}`);
export const jobDownloadUrl = (jobId: string) => `/api/jobs/${jobId}/download`;
// A pes_scan master's per-image sub-jobs, in path order -- see
// server/routes/jobs.py's get_scan_children.
export const getJobChildren = (jobId: string) => request<JobRow[]>(`/api/jobs/${jobId}/children`);

// POST (not a plain artifact GET), so a download needs a fetch+blob
// round-trip rather than a plain <a href download> link -- used for the
// two chart kinds that only exist as an inline SVG in the frontend today
// (see server/routes/jobs.py's render_plot).
export async function downloadPlotPng(
  jobId: string, kind: "optimization_energy" | "uvvis_inline", filename: string,
): Promise<void> {
  const res = await fetch(`/api/jobs/${jobId}/render_plot`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ kind }),
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      detail = (await res.json()).detail ?? detail;
    } catch {
      /* body wasn't JSON */
    }
    throw new ApiError(res.status, detail);
  }
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

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
export const addKbSourceText = (text: string, docType: "manual" | "paper", filename?: string) =>
  request<KbSource>("/api/kb/sources/text", {
    method: "POST",
    body: JSON.stringify({ text, doc_type: docType, filename: filename ?? null }),
  });
export const addKbSourceUrl = (url: string, docType: "manual" | "paper") =>
  request<KbSource>("/api/kb/sources/url", {
    method: "POST",
    body: JSON.stringify({ url, doc_type: docType }),
  });
export const kbSourceContentUrl = (source: string) => `/api/kb/sources/${encodeURIComponent(source)}/content`;

// --- Dynamic tools -----------------------------------------------------
export const listTools = () => request<DynamicTool[]>("/api/tools");
export const deleteTool = (name: string) =>
  request<{ deleted: boolean }>(`/api/tools/${encodeURIComponent(name)}`, { method: "DELETE" });

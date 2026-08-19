// Thin fetch wrappers over server/'s REST endpoints. Relative paths (e.g.
// "/api/threads") are proxied to the FastAPI backend by Vite's dev server
// (see vite.config.ts) so no base URL/CORS handling is needed here.
import { downloadBlob } from "./download";

export interface ThreadSummary {
  thread_id: string;
  label: string;
  created_at: number;
  last_active_at: number;
  active_job_ids: string[];
  pinned: boolean;
}

// Structured payload on a message the backend wrote directly rather than
// the model producing -- currently the failed-job notice (see
// app/agent/graph.py's append_notice). Carried as data so the UI renders a
// card instead of pattern-matching on prose, which would break the first
// time the wording changed.
export interface MessageNotice {
  kind: "job_failed";
  job_id: string;
  action?: "troubleshoot";
}

export interface ChatMessage {
  id: string | null;
  type: "HumanMessage" | "AIMessage" | "ToolMessage" | "SystemMessage";
  content: string;
  name: string | null;
  tool_call_id: string | null;
  tool_calls: { name: string; args: Record<string, unknown>; id: string }[];
  notice?: MessageNotice | null;
}

export interface PendingApproval {
  kind: "job_approval";
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

export interface MoleculeFrame {
  id: string;
  molecule: MoleculeDict;
  description: string;
}

export interface ThreadState {
  messages: ChatMessage[];
  molecule: MoleculeDict | null;
  molecule_frames: MoleculeFrame[];
  active_job_ids: string[];
  pending_approval: PendingApproval | null;
}

export interface JobRow {
  job_id: string;
  status: "pending" | "running" | "completed" | "failed" | "cancelled";
  message: string;
  updated_at: number | null;
  created_at: number | null;
  // The level of theory (hf/dft/mp2/ccsd/eom_ccsd/casscf/caspt2), or "" for
  // a task with none (blind: raw text only). NOT the runner key -- which
  // build/run function produced this job is derived only at dispatch time
  // (see app/chemistry/jobs/dispatch.py) and is never persisted here.
  method: string | null;
  // The v2 taxonomy: what the user actually asked for, separate from the
  // level of theory. No on-disk job is expected to have an empty task --
  // Phase 1 wiped every job predating the taxonomy switch -- so renderers
  // should treat "" here as a real absence to handle defensively, not as
  // an expected legacy case.
  task: string;
  subtype: string;
  engine: string | null;
  label: string;
  // The one authoritative download-filename stem, computed server-side by
  // app/chemistry/jobs/naming.py -- see lib/jobFilename.ts.
  filename_stem: string;
  params: Record<string, unknown>;
  // True for a pes_scan "master" job -- see server/routes/jobs.py's
  // is_scan_master. Its own per-image sub-jobs (parent_job_id set) never
  // appear in any job list, only via getJobChildren below.
  is_scan_master: boolean;
  // Same idea, for a wigner_ensemble master's per-sample sub-jobs.
  is_ensemble_master: boolean;
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

// Geometry (.xyz) or blind engine-input (.inp/.input/.json) upload -- see
// app/uploads/store.py. `sniff` is only populated for a .xyz upload, and
// is the SOLE authority for how many geometries it holds and what attach
// does with it (server/routes/chat.py's attach_upload); the frontend never
// re-parses the file to re-decide this.
export interface UploadRecord {
  id: string;
  original_name: string;
  extension: string;
  size_bytes: number;
  uploaded_at: number;
  sniff: { n_geometries: number; kind: "single" | "pair" | "set" } | null;
  owner: string | null;
}

// What POST .../attach_upload returns -- a 1/2-geometry upload comes back
// as new molecule_frames (kind="frames", the full post-attach thread
// state so the panel can render the newly-active molecule immediately); a
// 3+-geometry upload comes back as a geometry_set job id plus the
// checkpointed notice message that announces it in the conversation.
export interface AttachUploadResult {
  kind: "frames" | "geometry_set";
  frame_ids?: string[];
  job_id?: string;
  state?: ThreadState;
  message?: ChatMessage;
}

export interface StorageQuota {
  used_bytes: number;
  quota_bytes: number;
}

export class ApiError extends Error {
  status: number;
  constructor(status: number, detail: string) {
    super(detail);
    this.status = status;
  }
}

// AuthGate's own getMe query is the ONLY place in the app that reacted to
// a 401 before this -- every other authenticated call (sending a chat
// message, submitting a job, an admin action) just threw an ApiError that
// its own call site may or may not have surfaced, with no path back to
// the login screen short of a full manual page reload. Confirmed via a
// real two-device test: superseding a session in one browser context left
// the other showing a normal-looking (but now-broken) UI until reloaded.
//
// main.tsx calls registerAuthErrorHandler() once with a callback that
// invalidates the ["auth","me"] query -- api.ts doesn't import
// @tanstack/react-query itself (this file has no other dependency on it,
// and importing just for this would be a bigger change than a single
// callback needs) so the wiring stays a plain function reference instead.
let onAuthError: (() => void) | null = null;
export function registerAuthErrorHandler(handler: () => void): void {
  onAuthError = handler;
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
    if (res.status === 401 && path !== "/api/auth/me") {
      // getMe's OWN 401 is handled by AuthGate's normal query-error branch
      // already -- re-triggering it here too would just be a redundant
      // second invalidation of the query that's already in the middle of
      // producing this exact error.
      onAuthError?.();
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
export const postMessage = (threadId: string, text: string, jobIds: string[] = [], frameId: string | null = null) =>
  request<{ accepted: boolean }>(`/api/threads/${threadId}/messages`, {
    method: "POST",
    body: JSON.stringify({ text, job_ids: jobIds, frame_id: frameId }),
  });
export const stopTurn = (threadId: string) =>
  request<{ accepted: boolean }>(`/api/threads/${threadId}/stop`, { method: "POST" });
// Starts an investigation of a failed job, at the user's explicit request.
// Nothing investigates anything until this is called -- see the failure
// flow in docs/ARCHITECTURE.md. 409 means the job did not fail.
export const troubleshootJob = (threadId: string, jobId: string) =>
  request<{ accepted: boolean }>(`/api/threads/${threadId}/troubleshoot/${jobId}`, {
    method: "POST",
  });
export const approveJob = (threadId: string, approved: boolean, inputText?: string | null) =>
  request<{ resumed: boolean }>(`/api/threads/${threadId}/approvals/job`, {
    method: "POST",
    body: JSON.stringify({ approved, input_text: inputText ?? null }),
  });
export const resetMolecule = (threadId: string) =>
  request<ThreadState>(`/api/threads/${threadId}/molecule/reset`, { method: "POST" });
export const deleteMoleculeFrame = (threadId: string, frameId: string) =>
  request<ThreadState>(`/api/threads/${threadId}/molecule/frames/${frameId}`, { method: "DELETE" });
// Builds a relaxed 3D conformer from a 2D-sketcher-exported molfile
// (RDKit topology parse + ETKDG/MMFF94, see molecule_from_molblock) and
// adds it as the newest, active molecule frame.
export const buildMolecule = (threadId: string, molblock: string, charge?: number | null, multiplicity?: number | null) =>
  request<ThreadState>(`/api/threads/${threadId}/molecule/build`, {
    method: "POST",
    body: JSON.stringify({ molblock, charge: charge ?? null, multiplicity: multiplicity ?? null }),
  });

// --- Jobs ------------------------------------------------------------------
export const listJobs = (threadId: string) => request<JobRow[]>(`/api/threads/${threadId}/jobs`);
// Global, cross-thread job list -- backs the persistent Job Manager panel,
// distinct from listJobs() above (one conversation's active_job_ids only).
export const listAllJobs = () => request<JobRow[]>("/api/jobs");
export const getJobsQuota = () => request<StorageQuota>("/api/jobs/quota");
export const getJob = (jobId: string) => request<JobRow>(`/api/jobs/${jobId}`);
export const renameJob = (jobId: string, label: string) =>
  request<JobRow>(`/api/jobs/${jobId}`, { method: "PATCH", body: JSON.stringify({ label }) });
export const deleteJob = (jobId: string) => request<{ deleted: boolean }>(`/api/jobs/${jobId}`, { method: "DELETE" });
export const cancelJob = (jobId: string) =>
  request<{ cancelled: boolean } & JobRow>(`/api/jobs/${jobId}/cancel`, { method: "POST" });
export const jobArtifactUrl = (jobId: string, key: string) => `/api/jobs/${jobId}/artifacts/${key}`;
export const orbitalCubeUrl = (jobId: string, index: number, spin?: string | null, gbw?: string | null) => {
  const params = new URLSearchParams();
  if (spin) params.set("spin", spin);
  if (gbw) params.set("gbw", gbw);
  const qs = params.toString();
  return `/api/jobs/${jobId}/orbitals/${index}/cube${qs ? `?${qs}` : ""}`;
};
// Live, uncached "current iteration" path for a still-running neb_ts job
// -- see server/routes/jobs.py's get_neb_frames_live. Once the job
// completes, use jobArtifactUrl(jobId, "neb_frames") instead (the
// finalized, TS-first combined path).
export const nebLiveFramesUrl = (jobId: string) => `/api/jobs/${jobId}/neb_frames_live`;
export const getJobLog = (jobId: string, lines = 20) =>
  request<{ lines: string[] }>(`/api/jobs/${jobId}/log?lines=${lines}`);
export const jobDownloadUrl = (jobId: string) => `/api/jobs/${jobId}/download`;
export const jobRawInputUrl = (jobId: string) => `/api/jobs/${jobId}/raw_input`;
// A pes_scan master's per-image sub-jobs, in path order -- see
// server/routes/jobs.py's get_scan_children.
export const getJobChildren = (jobId: string) => request<JobRow[]>(`/api/jobs/${jobId}/children`);

// POST (not a plain artifact GET), so a download needs a fetch+blob
// round-trip rather than a plain <a href download> link -- used for the
// two chart kinds that only exist as an inline SVG in the frontend today
// (see server/routes/jobs.py's render_plot).
export async function downloadPlotPng(
  jobId: string, kind: "optimization_energy" | "uvvis_inline" | "ir_spectrum_inline", filename: string,
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
  downloadBlob(await res.blob(), filename);
}

// --- Job registry ------------------------------------------------------

// --- Knowledge base ------------------------------------------------------
export const getKbSources = () => request<KbSource[]>("/api/kb/sources");
export const getKbQuota = () => request<StorageQuota>("/api/kb/quota");
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
// ignoreRobots re-sends a URL the backend refused because the site's own
// robots.txt asks not to be ingested (F-002). The refusal is a 409 carrying
// the site's stated reason; this is the operator's explicit override of it.
export const addKbSourceUrl = (
  url: string,
  docType: "manual" | "paper",
  ignoreRobots = false,
) =>
  request<KbSource>("/api/kb/sources/url", {
    method: "POST",
    body: JSON.stringify({ url, doc_type: docType, ignore_robots: ignoreRobots }),
  });
export const kbSourceContentUrl = (source: string) => `/api/kb/sources/${encodeURIComponent(source)}/content`;

// --- Uploads (geometry / blind-input files) -------------------------------
export const getUploads = () => request<UploadRecord[]>("/api/uploads");
export const getUploadsQuota = () => request<StorageQuota>("/api/uploads/quota");
export const addUpload = (file: File) => {
  const form = new FormData();
  form.append("file", file);
  return request<UploadRecord>("/api/uploads", { method: "POST", body: form });
};
export const deleteUpload = (uploadId: string) =>
  request<{ deleted: string }>(`/api/uploads/${uploadId}`, { method: "DELETE" });
export const clearUploads = () => request<{ deleted: string[] }>("/api/uploads", { method: "DELETE" });
export const uploadContentUrl = (uploadId: string) => `/api/uploads/${uploadId}/content`;
// Attaches an uploaded .xyz file into a conversation -- 1/2 geometries
// become molecule_frames, 3+ become a geometry_set job (see
// server/routes/chat.py's attach_upload).
export const attachUpload = (threadId: string, uploadId: string) =>
  request<AttachUploadResult>(`/api/threads/${threadId}/attach_upload`, {
    method: "POST",
    body: JSON.stringify({ upload_id: uploadId }),
  });
// Pulls geometry #frameIndex (1-based) out of a job's own path_xyz
// artifact (a geometry_set, or any pes_1d/interp_pes/wigner_spectra
// master) and attaches it as the active molecule frame.
export const tagJobFrame = (threadId: string, jobId: string, frameIndex: number) =>
  request<{ frame_id: string; state: ThreadState }>(`/api/threads/${threadId}/tag_job_frame`, {
    method: "POST",
    body: JSON.stringify({ job_id: jobId, frame_index: frameIndex }),
  });

// --- Auth ----------------------------------------------------------------
// Session is an HttpOnly cookie, not a bearer token -- the browser attaches
// it automatically on every same-origin fetch() (default credentials mode
// is "same-origin", not "omit"), so none of these need special header
// handling beyond what request() already does. This is also why SSE
// (lib/sse.ts's plain EventSource, which can't carry custom headers at
// all) and every bare <img src>/<a href> job-artifact URL in this app
// authenticate for free once a session cookie exists.
export interface CurrentUser {
  id: string;
  email: string;
  username: string;
  role: "user" | "admin";
}

export const getMe = () => request<CurrentUser>("/api/auth/me");
export const login = (emailOrUsername: string, password: string) =>
  request<CurrentUser>("/api/auth/login", {
    method: "POST",
    body: JSON.stringify({ email_or_username: emailOrUsername, password }),
  });
export const register = (inviteToken: string, email: string, username: string, password: string) =>
  request<CurrentUser>("/api/auth/register", {
    method: "POST",
    body: JSON.stringify({ invite_token: inviteToken, email, username, password }),
  });
export const logout = () => request<{ logged_out: boolean }>("/api/auth/logout", { method: "POST" });
export const changePassword = (currentPassword: string, newPassword: string) =>
  request<{ changed: boolean }>("/api/auth/change-password", {
    method: "POST",
    body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }),
  });
/** Always multipart, with or without screenshots, so the route has one shape
 *  rather than a JSON branch and a form branch. `request` already omits the
 *  JSON content-type header when the body is FormData. */
export const submitBugReport = (body: string, files: File[] = []) => {
  const form = new FormData();
  form.append("body", body);
  for (const f of files) form.append("files", f);
  return request<{ id: string; created_at: string; attachments: number }>("/api/bug-reports", {
    method: "POST",
    body: form,
  });
};

// --- Admin -----------------------------------------------------------------
// Every function below hits an admin-only route (server/routes/admin.py) --
// a non-admin caller gets a 403 before any of these are ever reachable in
// the UI (AdminPanel.tsx is only mounted when useAuth().user?.role ===
// "admin"), so these don't attempt their own role gating client-side.

export interface AdminConfig {
  per_user_kb_quota_bytes: number;
  per_user_jobs_and_chat_quota_bytes: number;
  global_storage_quota_bytes: number;
  max_concurrent_jobs_total: number;
  max_concurrent_jobs_per_user: number;
  public_access_enabled: boolean;
  // Read-only: the hard ceiling max_concurrent_jobs_total can never
  // exceed, since it's also JobManager's fixed worker-pool size (see
  // server/routes/admin.py's patch_config).
  max_concurrent_jobs_pool_size: number;
}

export const getAdminConfig = () => request<AdminConfig>("/api/admin/config");
export const patchAdminConfig = (key: keyof AdminConfig, value: number | boolean) =>
  request<{ key: string; value: number | boolean }>("/api/admin/config", {
    method: "PATCH",
    body: JSON.stringify({ key, value }),
  });
export const togglePublicAccess = () =>
  request<{ public_access_enabled: boolean }>("/api/admin/toggle-public-access", { method: "POST" });

export interface AdminUserUsage {
  user_id: string;
  username: string;
  email: string;
  kb_bytes: number;
  kb_quota_bytes: number;
  job_bytes: number;
  chat_bytes: number;
  jobs_and_chat_bytes: number;
  jobs_and_chat_quota_bytes: number;
  total_bytes: number;
}

export interface AdminStorageReport {
  per_user: AdminUserUsage[];
  global: {
    kb_bytes: number;
    job_bytes: number;
    chat_bytes: number;
    total_bytes: number;
    quota_bytes: number;
  };
  quota_config: AdminConfig;
}

export const getAdminStorage = () => request<AdminStorageReport>("/api/admin/storage");

export const purgeAllJobs = () => request<{ purged_job_ids: string[]; count: number }>("/api/admin/purge/jobs", { method: "POST" });
export const purgeAllKb = () => request<{ purged_sources: string[]; count: number }>("/api/admin/purge/kb", { method: "POST" });
export const purgeAllThreads = (includePinned = false) =>
  request<{ purged_thread_ids: string[]; count: number }>("/api/admin/purge/threads", {
    method: "POST",
    body: JSON.stringify({ include_pinned: includePinned }),
  });

export interface AdminAuditLogEntry {
  id: string;
  actor_user_id: string | null;
  action: string;
  target: string | null;
  details: Record<string, unknown> | null;
  created_at: string;
}

export const getAdminAuditLog = () => request<AdminAuditLogEntry[]>("/api/admin/audit-log");

export interface AdminUserRow {
  id: string;
  email: string;
  username: string;
  role: "user" | "admin";
  is_active: boolean;
  created_at: string;
  last_login_at: string | null;
}

export const listAdminUsers = () => request<AdminUserRow[]>("/api/admin/users");

export const deleteAdminUser = (userId: string) =>
  request<{
    deleted: boolean;
    purged_jobs: number;
    purged_kb_sources: number;
    purged_threads: number;
  }>(`/api/admin/users/${userId}`, { method: "DELETE" });

export const setAdminUserActive = (userId: string, isActive: boolean) =>
  request<AdminUserRow>(`/api/admin/users/${userId}`, {
    method: "PATCH",
    body: JSON.stringify({ is_active: isActive }),
  });

// --- Invites ---------------------------------------------------------------

export interface AdminInviteRow {
  token: string;
  role: "user" | "admin";
  email_hint: string | null;
  expires_at: string;
  created_at: string;
  created_by: string | null;
  created_by_username: string | null;
  redeemed_by: string | null;
  redeemed_by_username: string | null;
  redeemed_at: string | null;
  revoked_at: string | null;
}

// POST /invites returns create_invite_token's narrower RETURNING clause --
// no join columns -- so it is deliberately typed separately rather than as
// an AdminInviteRow the caller would then find half-empty.
export interface AdminInviteCreated {
  token: string;
  role: "user" | "admin";
  email_hint: string | null;
  expires_at: string;
  created_at: string;
}

export const listAdminInvites = () => request<AdminInviteRow[]>("/api/admin/invites");

export const createAdminInvite = (
  role: "user" | "admin",
  emailHint: string | null,
  ttlHours: number,
) =>
  request<AdminInviteCreated>("/api/admin/invites", {
    method: "POST",
    body: JSON.stringify({ role, email_hint: emailHint, ttl_hours: ttlHours }),
  });

export const revokeAdminInvite = (token: string) =>
  request<AdminInviteRow>(`/api/admin/invites/${token}/revoke`, { method: "POST" });

// --- Bug reports -----------------------------------------------------------

export interface BugReportAttachment {
  id: string;
  original_name: string;
  content_type: string;
  size_bytes: number;
}

export interface AdminBugReport {
  id: string;
  user_id: string | null;
  // NULL when the reporter's account has since been deleted -- bug_reports.user_id
  // is ON DELETE SET NULL, so reports outlive their reporter on purpose.
  reporter_username: string | null;
  body: string;
  status: "open" | "closed";
  archived_at: string | null;
  created_at: string;
  attachments: BugReportAttachment[];
}

export const listAdminBugReports = () => request<AdminBugReport[]>("/api/admin/bug-reports");

/** Status and archived are independent and both optional; the route requires
 *  at least one. Archiving without restating the status is the point -- see
 *  BugReportPatchIn in server/routes/admin.py. */
export const patchAdminBugReport = (
  reportId: string,
  patch: { status?: "open" | "closed"; archived?: boolean },
) =>
  request<{ id: string; status: string | null; archived: boolean | null }>(
    `/api/admin/bug-reports/${reportId}`,
    { method: "PATCH", body: JSON.stringify(patch) },
  );

export const deleteAdminBugReport = (reportId: string) =>
  request<void>(`/api/admin/bug-reports/${reportId}`, { method: "DELETE" });

/** Same-origin URL; the httpOnly SameSite=Lax session cookie rides along on
 *  an <img src>, exactly as the job-artifact images already do. */
export const bugAttachmentUrl = (attachmentId: string) =>
  `/api/admin/bug-reports/attachments/${attachmentId}`;

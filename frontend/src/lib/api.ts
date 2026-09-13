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
  // "job_failed" is the card with the Troubleshoot button. "job_cancelled",
  // "job_submitted" and "job_rejected" are app-written assistant messages
  // that read as ordinary replies and need no special chrome; they carry a
  // kind so tests and any future UI can tell them from model text.
  // "system_notice" is the one that changes rendering: it marks text the
  // app injected as a HumanMessage because the model needs a user turn to
  // answer, which the UI must NOT show as words the user typed.
  kind: "job_failed" | "job_cancelled" | "job_submitted" | "job_rejected"
      | "geometry_set_attached" | "system_notice";
  job_id?: string;
  job_ids?: string[];
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
  /** The conversation this job belongs to, or null for one submitted
   *  outside any. Present only on the single-job GET; the list routes strip
   *  it. See queries.ts's useJobQuery for what reads it (R-027). */
  thread_id?: string | null;
  status: "pending" | "running" | "completed" | "failed" | "cancelled";
  message: string;
  updated_at: number | null;
  created_at: number | null;
  // The level of theory (hf/dft/mp2/ccsd/eom_ccsd/casscf/caspt2/nevpt2/
  // mcpdft/lpdft), or "" for
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
  // The username of whoever shared this job, on a copy accepted from
  // another user; null on a job this account ran itself. Drives the
  // "Shared by" badge in JobManagerPanel.
  shared_from: string | null;
  params: Record<string, unknown>;
  // Which children-fetching/rendering shape this job needs, or null for
  // an ordinary job (or a childless master like geometry_set) -- see
  // server/routes/jobs.py's _master_kind. P7.4: one field rather than a
  // separate is_scan_master/is_ensemble_master/is_batch_master boolean
  // per kind. A master's own children (parent_job_id set) never appear
  // in any job list, only via getJobChildren below.
  master_kind: "scan" | "ensemble" | "batch" | null;
  parent_job_id: string | null;
  // Which project archive this job is filed into, or null for one that is
  // not archived. Only present when listAllJobs is asked for archived jobs
  // (includeArchived) -- the default list omits archived jobs entirely, so
  // there would be nothing for these to say. See app/projects/registry.py.
  project_id?: string | null;
  project_name?: string | null;
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

// What POST .../attach_upload returns -- a 1/2-geometry .xyz upload comes
// back as new molecule_frames (kind="frames", the full post-attach thread
// state so the panel can render the newly-active molecule immediately); a
// 3+-geometry .xyz upload comes back as a geometry_set job id plus the
// checkpointed notice message that announces it in the conversation. A
// blind-input (.inp/.input/.json) upload (P9.6) comes back as kind=
// "raw_file" plus the synthetic HumanMessage carrying the file's own
// content, appended to the conversation the same no-LLM way.
export interface AttachUploadResult {
  kind: "frames" | "geometry_set" | "raw_file";
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

// The deployment is mid-update. Every polling query in the app hits this
// within seconds of maintenance mode going on -- the jobs list alone refetches
// every four seconds -- so this doubles as the broadcast channel that tells
// every open tab an update has started. There is no app-level event stream to
// build: the polling that already exists is the notification.
let onMaintenance: ((message: string) => void) | null = null;
export function registerMaintenanceHandler(handler: (message: string) => void): void {
  onMaintenance = handler;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    ...init,
    headers: init?.body instanceof FormData ? init.headers : { "Content-Type": "application/json", ...init?.headers },
  });
  if (!res.ok) {
    let detail = res.statusText;
    // Read once as text: a Response body can only be consumed once, and both
    // the maintenance branch and the generic error path below want it.
    const rawBody = await res.text().catch(() => "");
    try {
      const body = JSON.parse(rawBody);
      detail = body.detail ?? detail;
    } catch {
      /* body wasn't JSON -- fall back to statusText */
    }
    // Checked BEFORE the 401 branch below, and that order matters. During an
    // update every session is deliberately dropped, so a tab that treated the
    // maintenance response as an auth failure would bounce the user to a
    // login screen they cannot get past -- which looks exactly like the app
    // being broken rather than being updated.
    if (res.status === 503 && detail === "maintenance") {
      let message = "NexusQC is being updated and will be back shortly.";
      try {
        message = (JSON.parse(rawBody) as { message?: string }).message ?? message;
      } catch {
        /* the default sentence is fine */
      }
      onMaintenance?.(message);
      throw new ApiError(res.status, detail);
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
export const postMessage = (
  threadId: string,
  text: string,
  jobIds: string[] = [],
  frameId: string | null = null,
  plotIds: string[] = [],
) =>
  request<{ accepted: boolean }>(`/api/threads/${threadId}/messages`, {
    method: "POST",
    body: JSON.stringify({ text, job_ids: jobIds, frame_id: frameId, plot_ids: plotIds }),
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
// includeArchived brings back the jobs filed into a project archive, each
// row then carrying project_id/project_name. Off by default, matching the
// route: getting a finished study off this list is the point of archiving.
export const listAllJobs = (includeArchived = false) =>
  request<JobRow[]>(`/api/jobs${includeArchived ? "?include_archived=true" : ""}`);
export const getJobsQuota = () => request<StorageQuota>("/api/jobs/quota");
export const getJob = (jobId: string) => request<JobRow>(`/api/jobs/${jobId}`);
export const renameJob = (jobId: string, label: string) =>
  request<JobRow>(`/api/jobs/${jobId}`, { method: "PATCH", body: JSON.stringify({ label }) });
export const deleteJob = (jobId: string) => request<{ deleted: boolean }>(`/api/jobs/${jobId}`, { method: "DELETE" });
export const cancelJob = (jobId: string) =>
  request<{ cancelled: boolean } & JobRow>(`/api/jobs/${jobId}/cancel`, { method: "POST" });
export const jobArtifactUrl = (jobId: string, key: string) => `/api/jobs/${jobId}/artifacts/${key}`;

// --- Project archives ----------------------------------------------------
//
// A project is a named bundle of jobs, listed in the left rail. Archiving
// is a membership label and never moves a job's files, so everything here
// deals in ids. See app/projects/registry.py.

export interface ProjectRow {
  project_id: string;
  name: string;
  description: string;
  created_at: number;
  updated_at: number;
  job_ids: string[];
  job_count: number;
  size_bytes: number;
}

// The single-project GET additionally carries a row per member job, in the
// same shape the job manager's own list uses.
export interface ProjectDetail extends ProjectRow {
  jobs: JobRow[];
}

export const listProjects = () => request<ProjectRow[]>("/api/projects");
export const getProject = (projectId: string) => request<ProjectDetail>(`/api/projects/${projectId}`);
export const createProject = (name: string, jobIds: string[] = [], description = "") =>
  request<ProjectRow>("/api/projects", {
    method: "POST",
    body: JSON.stringify({ name, description, job_ids: jobIds }),
  });
export const updateProject = (projectId: string, patch: { name?: string; description?: string }) =>
  request<ProjectRow>(`/api/projects/${projectId}`, { method: "PATCH", body: JSON.stringify(patch) });
export const addProjectJobs = (projectId: string, jobIds: string[]) =>
  request<ProjectRow>(`/api/projects/${projectId}/jobs`, {
    method: "POST",
    body: JSON.stringify({ job_ids: jobIds }),
  });
// A POST rather than a DELETE with a body: this puts jobs back in the job
// manager rather than removing anything. See server/routes/projects.py.
export const removeProjectJobs = (projectId: string, jobIds: string[]) =>
  request<ProjectRow>(`/api/projects/${projectId}/jobs/remove`, {
    method: "POST",
    body: JSON.stringify({ job_ids: jobIds }),
  });
// deleteJobs has no default on the server for a reason: the two answers are
// genuinely different actions and the user is asked every time.
export const deleteProject = (projectId: string, deleteJobs: boolean) =>
  request<{ deleted: boolean; released_jobs: number; purged_jobs: number }>(
    `/api/projects/${projectId}?delete_jobs=${deleteJobs}`,
    { method: "DELETE" },
  );
export const purgeMyProjects = () =>
  request<{ purged_projects: number; purged_jobs: number }>("/api/projects/purge-mine", { method: "POST" });
export const projectDownloadUrl = (projectId: string) => `/api/projects/${projectId}/download`;

// A saved plot's image, by version rather than "the current one": a chat
// message cites the version it actually drew, so editing a plot cannot
// retroactively change what an older message appears to show. See
// app/plots/store.py.
export const plotImageUrl = (plotId: string, version: string) =>
  `/api/plots/${plotId}/versions/${version}.png`;
export const plotDownloadUrl = (plotId: string) => `/api/plots/${plotId}/download`;

// A saved plot, as the Plots panel lists it. `data` (the numbers the plot
// drew) is omitted from list rows and only present on the single-plot GET --
// it can run to a few hundred values and the panel only shows a thumbnail.
export interface PlotRow {
  plot_id: string;
  kind: string;
  label: string;
  job_ids: string[];
  origin: string;
  created_at: number;
  updated_at: number;
  versions: string[];
}

export const getPlots = () => request<PlotRow[]>("/api/plots");

// The single-plot GET, unlike the list, carries `spec` and `data` -- the
// numbers the plot drew. Only the flyout needs them.
export interface PlotDetail extends PlotRow {
  spec: Record<string, unknown>;
  data: { columns?: string[]; series?: Record<string, (number | null)[]> } & Record<string, unknown>;
}
export const getPlot = (plotId: string) => request<PlotDetail>(`/api/plots/${plotId}`);
export const renamePlot = (plotId: string, label: string) =>
  request<PlotRow>(`/api/plots/${plotId}`, { method: "PATCH", body: JSON.stringify({ label }) });
export const deletePlot = (plotId: string) =>
  request<{ deleted: string }>(`/api/plots/${plotId}`, { method: "DELETE" });
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
// A pes_1d/interp_pes/wigner_spectra master's per-image (or per-sample)
// sub-jobs, windowed -- see server/routes/jobs.py's get_scan_children
// (P7.3: paginated, trimmed rows, not every child at once).
export interface JobChildrenPage {
  total: number;
  offset: number;
  items: JobRow[];
}
export const getJobChildren = (jobId: string, offset = 0, limit = 100) =>
  request<JobChildrenPage>(`/api/jobs/${jobId}/children?offset=${offset}&limit=${limit}`);

// A wigner_spectra master's pooled raw transitions (P8.3's live broadening
// slider) -- fetched once, re-broadened client-side on every slider move
// with no further request. See server/routes/jobs.py's
// get_wigner_transitions for the pooling itself.
export interface WignerTransitionsResponse {
  pooled: {
    energies_eV: number[];
    oscillator_strengths: number[];
    state_indices: number[];
    sub_job_ids: string[];
  };
  diagnostics: {
    n_sub_jobs: number;
    n_completed: number;
    n_no_intensity: number;
    n_failed_or_pending: number;
    n_transitions_pooled: number;
  };
}
export const getWignerTransitions = (jobId: string) =>
  request<WignerTransitionsResponse>(`/api/jobs/${jobId}/wigner_transitions`);

// The filename a same-origin response asked to be saved under. Only the
// simple `filename="..."` form is parsed, which is the only form anything
// in this app emits (see server/routes/jobs.py's _attachment).
function filenameFromResponse(res: Response): string | null {
  const header = res.headers.get("content-disposition");
  return header?.match(/filename="([^"]+)"/)?.[1] ?? null;
}

// POST (not a plain artifact GET), so a download needs a fetch+blob
// round-trip rather than a plain <a href download> link -- used for the
// two chart kinds that only exist as an inline SVG in the frontend today
// (see server/routes/jobs.py's render_plot).
//
// The name comes off the response rather than from the caller: render_plot
// already builds one, and a caller-supplied name silently won over it, so
// the same bytes arrived under two different names depending on whether a
// button or the bare route produced them.
/** Report a raw `fetch` response to the same 401 and maintenance handlers
 *  `request()` uses, and throw if it failed.
 *
 *  R-095. Several call sites cannot go through `request()` -- they want a
 *  Blob, a raw text body, or a streamed artifact rather than parsed JSON --
 *  and so they bypassed the two hooks that live in it. A session that
 *  expired while a job drawer was open therefore produced an inline
 *  "Couldn't load orbital: 401 Unauthorized" and left the user staring at an
 *  app that was no longer logged in, instead of the login screen any
 *  request()-routed call would have taken them to. Maintenance mode had the
 *  same shape: the overlay never appeared for these.
 *
 *  Every raw fetch in this app now passes its response through here. */
export async function checkRawResponse(res: Response, what: string): Promise<Response> {
  if (res.ok) return res;
  let detail = res.statusText;
  try {
    detail = (await res.clone().json()).detail ?? detail;
  } catch {
    /* body wasn't JSON */
  }
  if (res.status === 503 && detail === "maintenance") {
    onMaintenance?.("NexusQC is being updated and will be back shortly.");
  }
  if (res.status === 401) {
    onAuthError?.();
  }
  throw new ApiError(res.status, `${what}: ${detail}`);
}

export async function downloadPlotPng(
  jobId: string, kind: "optimization_energy" | "uvvis_inline" | "ir_spectrum_inline",
  jobFilenameStem?: string,
): Promise<void> {
  const res = await checkRawResponse(
    await fetch(`/api/jobs/${jobId}/render_plot`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ kind }),
    }),
    "Couldn't render the plot",
  );
  // The server's own Content-Disposition first, and only then a fallback --
  // which now follows the app's naming rule (safename_descriptor.extension,
  // app/chemistry/jobs/naming.py) rather than inventing `<job id>_<kind>`.
  // R-095: a user who hit the fallback got a file named after an opaque
  // twelve-hex-character id, which is the one thing the naming rule exists
  // to keep out of a downloads folder.
  const stem = jobFilenameStem ?? jobId;
  downloadBlob(await res.blob(), filenameFromResponse(res) ?? `${stem}_${kind}.png`);
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
export const register = (
  inviteToken: string,
  email: string,
  username: string,
  password: string,
  firstName: string,
  lastName: string,
) =>
  request<CurrentUser>("/api/auth/register", {
    method: "POST",
    body: JSON.stringify({
      invite_token: inviteToken, email, username, password,
      first_name: firstName, last_name: lastName,
    }),
  });
export const logout = () => request<{ logged_out: boolean }>("/api/auth/logout", { method: "POST" });
export const changePassword = (currentPassword: string, newPassword: string) =>
  request<{ changed: boolean }>("/api/auth/change-password", {
    method: "POST",
    body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }),
  });
export const purgeMyData = () =>
  request<{ purged: boolean; purged_jobs: number; purged_kb_sources: number; purged_uploads: number }>(
    "/api/auth/purge-my-data",
    { method: "POST" },
  );
/** Cookie-authenticated GET, same convention as jobDownloadUrl -- a plain
 *  anchor href, not fetch+blob (see download_my_data's own docstring in
 *  server/routes/auth.py for why the response is never written to disk
 *  server-side either). */
export const downloadMyDataUrl = () => "/api/auth/download-my-data";
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
  // Read-only: the hard ceiling max_concurrent_jobs_total can never
  // exceed, since it's also JobManager's fixed worker-pool size (see
  // server/routes/admin.py's patch_config).
  max_concurrent_jobs_pool_size: number;
}

export interface VersionInfo {
  commit: string;
}

// Unauthenticated and outside the admin surface on purpose: it has to answer
// while the deployment has no auth layer, and it says nothing a visitor could
// not read off the public repository.
export const getVersion = () => request<VersionInfo>("/api/version");

// The commit this bundle was compiled from, baked in by vite.config.ts's
// `define` at build time. 'unknown' is what a host `npm run build` with no
// stamp produces, and means "cannot tell" -- never a reason to tell somebody
// their tab is out of date.
export const BUILD_SHA: string = typeof __BUILD_SHA__ === "string" ? __BUILD_SHA__ : "unknown";

export interface AdminDeployment {
  api_commit: string;
  api_commit_known: boolean;
  runner: RunnerState;
  history: UpdateLogEntry[];
}

export interface AdminActivityUser {
  id: string;
  username: string | null;
  email: string | null;
  role: string | null;
  is_active: boolean | null;
  last_login_at: string | null;
  running_jobs: number;
  pending_jobs: number;
  open_streams: number;
  would_be_interrupted: boolean;
  is_you: boolean;
}

export interface AdminActivity {
  users: AdminActivityUser[];
  unowned: { running_jobs: number; pending_jobs: number; open_streams: number };
  totals: {
    running_jobs: number;
    pending_jobs: number;
    open_streams: number;
    users_interrupted: number;
    others_interrupted: number;
  };
}

export interface RunnerState {
  installed: boolean;
  alive: boolean;
  last_seen: number | null;
  age_seconds?: number;
}

export interface UpdateLogEntry {
  verb: string;
  at: string;
  to: string;
  from: string;
}

export interface DestructiveFinding {
  severity: "destructive" | "warn" | "ok" | "skipped";
  title: string;
  detail: string;
}

export interface DeployRun {
  id: string;
  status: {
    state?: "queued" | "running" | "done" | "failed";
    step?: string;
    error?: string;
    target?: string;
    destructive?: number;
    exit_code?: number;
  };
  request: { action?: string; ref?: string; drain?: boolean; force?: boolean } | null;
  report: {
    from: string;
    to: string;
    destructive: number;
    warnings: number;
    findings: DestructiveFinding[];
  } | null;
  changes: string[];
  log: string;
}

export const postAdminDeploy = (body: {
  action: "ping" | "report" | "update" | "rollback";
  ref?: string;
  drain?: boolean;
  force?: boolean;
}) =>
  request<{ id: string; action: string }>("/api/admin/deploy", {
    method: "POST",
    body: JSON.stringify(body),
  });

export const getAdminDeploy = (id: string) => request<DeployRun>(`/api/admin/deploy/${id}`);

export const getAdminDeployment = () => request<AdminDeployment>("/api/admin/deployment");
export const getAdminActivity = () => request<AdminActivity>("/api/admin/activity");

export const getAdminConfig = () => request<AdminConfig>("/api/admin/config");
export const patchAdminConfig = (key: keyof AdminConfig, value: number | boolean) =>
  request<{ key: string; value: number | boolean }>("/api/admin/config", {
    method: "PATCH",
    body: JSON.stringify({ key, value }),
  });

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
  /** Job directories with no spec.json. Counted toward nobody's quota and
   * no global total, because app/chemistry/jobs/quota.py's _iter_job_ids()
   * skips them -- which is exactly why the console reports them separately
   * rather than folding them into the figures above. `held_back` is how
   * many were found but are too recently touched to sweep safely; see
   * _ORPHAN_DIR_MIN_AGE_SECONDS in app/auth/storage_quota.py. */
  orphaned_jobs: { job_ids: string[]; bytes: number; held_back: number };
  quota_config: AdminConfig;
}

export const getAdminStorage = () => request<AdminStorageReport>("/api/admin/storage");

export const purgeAllJobs = () => request<{ purged_job_ids: string[]; count: number }>("/api/admin/purge/jobs", { method: "POST" });
// Not part of the danger zone: this deletes no user's data. These
// directories are not jobs, nobody owns them, and nothing lists them.
export const purgeOrphanedJobs = () =>
  request<{ purged_job_ids: string[]; count: number; bytes: number; held_back: number }>(
    "/api/admin/purge/orphaned-jobs", { method: "POST" },
  );
export const purgeAllKb = () => request<{ purged_sources: string[]; count: number }>("/api/admin/purge/kb", { method: "POST" });
export const purgeAllThreads = (includePinned = false) =>
  request<{ purged_thread_ids: string[]; count: number }>("/api/admin/purge/threads", {
    method: "POST",
    body: JSON.stringify({ include_pinned: includePinned }),
  });

export interface AdminAuditLogEntry {
  id: string;
  actor_user_id: string | null;
  /** The actor's username as it was when the action happened, captured at
   * write time. The audit log has no foreign key to users, so this is the
   * only thing that stays readable once an account is deleted. Null on
   * rows written before the column existed. */
  actor_username: string | null;
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
  first_name: string;
  last_name: string;
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
  created_by_first_name: string | null;
  created_by_last_name: string | null;
  redeemed_by: string | null;
  redeemed_by_username: string | null;
  redeemed_by_first_name: string | null;
  redeemed_by_last_name: string | null;
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

// --- Password resets -------------------------------------------------------
//
// No mail server here, so a reset is issued by an admin and handed over out
// of band; the person redeems it at /?reset=<token>. Same deep-link contract
// as an invite.

export interface AdminPasswordResetRow {
  token: string;
  user_id: string;
  created_by: string | null;
  created_by_username: string | null;
  for_username: string | null;
  expires_at: string;
  created_at: string;
  used_at: string | null;
  revoked_at: string | null;
}

// POST returns the narrower RETURNING clause plus the target's username --
// no join columns -- so it is typed separately, as AdminInviteCreated is.
export interface AdminPasswordResetCreated {
  token: string;
  user_id: string;
  username: string;
  expires_at: string;
  created_at: string;
}

export const listAdminPasswordResets = () =>
  request<AdminPasswordResetRow[]>("/api/admin/password-resets");

export const createAdminPasswordReset = (userId: string, ttlHours: number) =>
  request<AdminPasswordResetCreated>(`/api/admin/users/${userId}/password-reset`, {
    method: "POST",
    body: JSON.stringify({ ttl_hours: ttlHours }),
  });

export const revokeAdminPasswordReset = (token: string) =>
  request<AdminPasswordResetRow>(`/api/admin/password-resets/${token}/revoke`, {
    method: "POST",
  });

// Unauthenticated on purpose: the caller cannot sign in, which is the point.
// Succeeds into a live session, so the caller is signed in afterwards exactly
// as register() leaves them.
export const resetPassword = (token: string, newPassword: string) =>
  request<CurrentUser>("/api/auth/reset-password", {
    method: "POST",
    body: JSON.stringify({ token, new_password: newPassword }),
  });

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


// --- Sharing ---------------------------------------------------------------
//
// A share hands the recipient a real COPY of the job under a new id they
// own, not a reference to the sender's. That is what lets them keep the
// result after the sender deletes theirs, and it is why nothing here needs
// a notion of shared-but-not-owned anywhere else in this client: an
// accepted share simply becomes an ordinary JobRow.

// Deliberately narrower than CurrentUser and AdminUserRow: the share
// picker is the first place one ordinary user learns another exists, and
// it publishes no email and no role. See app/auth/models.py's search_users.
export interface UserSearchRow {
  id: string;
  username: string;
  first_name: string;
  last_name: string;
}

export interface ShareRow {
  share_id: string;
  kind: "job" | "project";
  resource_id: string;
  from_user_id: string;
  to_user_id: string;
  status: "pending" | "accepted" | "declined" | "withdrawn";
  note: string;
  // Label and size are snapshotted at offer time, so an inbox row still
  // reads sensibly after the sender renamed or deleted the original.
  source_label: string;
  size_bytes: number;
  created_at: number | null;
  resolved_at: number | null;
  // What an accept produced: the recipient's own job or project id.
  copied_resource_id: string | null;
  from_username: string | null;
  from_first_name: string | null;
  from_last_name: string | null;
  to_username: string | null;
}

export const searchUsers = (q: string) =>
  request<UserSearchRow[]>(`/api/users/search?q=${encodeURIComponent(q)}`);

export const createShare = (
  kind: "job" | "project",
  resourceId: string,
  toUserId: string,
  note = "",
) =>
  request<ShareRow>("/api/shares", {
    method: "POST",
    body: JSON.stringify({ kind, resource_id: resourceId, to_user_id: toUserId, note }),
  });

export const listShareInbox = () => request<ShareRow[]>("/api/shares/inbox");
export const listShareOutbox = () => request<ShareRow[]>("/api/shares/outbox");
export const acceptShare = (shareId: string) =>
  request<ShareRow>(`/api/shares/${shareId}/accept`, { method: "POST" });
export const declineShare = (shareId: string) =>
  request<ShareRow>(`/api/shares/${shareId}/decline`, { method: "POST" });
export const withdrawShare = (shareId: string) =>
  request<ShareRow>(`/api/shares/${shareId}/withdraw`, { method: "POST" });

import { useEffect, useRef, useState } from "react";
import type { DragEvent } from "react";
import { Search, Trash2, Plus, X, Upload, FolderDown, Loader2, Paperclip, Layers } from "lucide-react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { CollapsibleSection } from "../app-shell/CollapsibleSection";
import { Flyout } from "../app-shell/Flyout";
import { DownloadButton } from "../app-shell/DownloadButton";
import { SearchableText, type SearchableTextHandle } from "../app-shell/SearchableText";
import { triggerDownload } from "../lib/download";
import { StorageUsageBadge } from "../app-shell/StorageUsageBadge";
import { useActiveThreadStore } from "../lib/activeThreadStore";
import { useChatStore } from "../lib/chatStore";
import {
  jobsListQueryKey, jobsQueryKey, uploadsQuotaQueryKey, uploadsQueryKey, useUploadsQuery, useUploadsQuotaQuery,
} from "../lib/queries";
import * as api from "../lib/api";
import type { UploadRecord } from "../lib/api";

// Kept in sync with app/uploads/store.py's ALLOWED_EXTENSIONS -- a fast
// client-side check to explain a rejection immediately; the backend
// re-validates regardless, since a drag gesture can carry any file.
const ALLOWED_EXTENSIONS = [".xyz", ".inp", ".input", ".json"];

function hasAllowedExtension(filename: string): boolean {
  const lower = filename.toLowerCase();
  return ALLOWED_EXTENSIONS.some((ext) => lower.endsWith(ext));
}

function sniffLabel(upload: UploadRecord): string | null {
  if (!upload.sniff) return null;
  const { n_geometries, kind } = upload.sniff;
  if (kind === "single") return "1 geometry";
  if (kind === "pair") return `${n_geometries} geometries (pair)`;
  return `${n_geometries} geometries (set)`;
}

function AddFilesForm({ onDone }: { onDone: () => void }) {
  const queryClient = useQueryClient();
  const fileRef = useRef<HTMLInputElement>(null);
  const [fileNames, setFileNames] = useState<string[]>([]);

  const addMutation = useMutation({
    mutationFn: async (files: File[]) => {
      for (const file of files) await api.addUpload(file);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: uploadsQueryKey });
      queryClient.invalidateQueries({ queryKey: uploadsQuotaQueryKey });
      onDone();
    },
  });

  const buttonLabel =
    fileNames.length === 0
      ? "Choose XYZ/INP/JSON files"
      : fileNames.length === 1
        ? fileNames[0]
        : `${fileNames.length} files selected`;

  return (
    <div className="flex flex-col gap-2 rounded border border-border bg-surface-raised p-2">
      <input
        ref={fileRef}
        type="file"
        accept=".xyz,.inp,.input,.json"
        multiple
        className="hidden"
        data-testid="files-section-file-input"
        onChange={(e) => setFileNames(Array.from(e.target.files ?? []).map((f) => f.name))}
      />
      <button
        onClick={() => fileRef.current?.click()}
        className="flex items-center gap-1.5 rounded border border-dashed border-border px-2 py-1.5 text-xs text-text-muted hover:border-accent hover:text-text"
      >
        <Upload size={12} />
        {buttonLabel}
      </button>
      <div className="flex gap-2">
        <button
          onClick={() => fileRef.current?.files?.length && addMutation.mutate(Array.from(fileRef.current.files))}
          disabled={fileNames.length === 0 || addMutation.isPending}
          className="rounded bg-accent px-2 py-1 text-xs text-white disabled:opacity-40"
        >
          {addMutation.isPending ? "Uploading..." : "Add"}
        </button>
        <button onClick={onDone} className="rounded px-2 py-1 text-xs text-text-muted hover:text-text">
          Cancel
        </button>
      </div>
      {addMutation.isError && <div className="text-xs text-status-failed">{String(addMutation.error)}</div>}
    </div>
  );
}

function FilePreviewFlyout({ upload, onClose }: { upload: UploadRecord; onClose: () => void }) {
  const [text, setText] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const searchRef = useRef<SearchableTextHandle>(null);

  useEffect(() => {
    setText(null);
    setError(null);
    fetch(api.uploadContentUrl(upload.id))
      .then((r) => (r.ok ? r.text() : Promise.reject(new Error(`HTTP ${r.status}`))))
      .then(setText)
      .catch((e) => setError(String(e)));
  }, [upload.id]);

  return (
    <Flyout
      open
      onClose={onClose}
      title={upload.original_name}
      widthClassName="w-140"
      headerActions={
        <DownloadButton
          title={`Download ${upload.original_name}`}
          testId="flyout-download-upload"
          onDownload={() => triggerDownload(api.uploadContentUrl(upload.id), upload.original_name)}
        />
      }
      onEscapeKeyDown={(e) => {
        if (searchRef.current?.hasQuery()) {
          e.preventDefault();
          searchRef.current.clear();
        }
      }}
    >
      {error ? (
        <div className="text-xs text-status-failed">{error}</div>
      ) : text == null ? (
        <div className="text-xs text-text-muted">Loading...</div>
      ) : (
        <SearchableText ref={searchRef} text={text} />
      )}
    </Flyout>
  );
}

export function FilesSection() {
  const [collapsed, setCollapsed] = useState(true);
  const [search, setSearch] = useState("");
  const [adding, setAdding] = useState(false);
  const [dragOver, setDragOver] = useState(false);
  const [previewUpload, setPreviewUpload] = useState<UploadRecord | null>(null);
  const [dropError, setDropError] = useState<string | null>(null);
  const [dropProgress, setDropProgress] = useState<{ done: number; total: number } | null>(null);
  const [attachError, setAttachError] = useState<string | null>(null);
  const [clearConfirming, setClearConfirming] = useState(false);
  const uploadsQuery = useUploadsQuery();
  const quotaQuery = useUploadsQuotaQuery();
  const queryClient = useQueryClient();
  const activeThreadId = useActiveThreadStore((s) => s.activeThreadId);
  const setMolecule = useChatStore((s) => s.setMolecule);
  const setMoleculeFrames = useChatStore((s) => s.setMoleculeFrames);
  const applyEvent = useChatStore((s) => s.applyEvent);

  const deleteMutation = useMutation({
    mutationFn: (uploadId: string) => api.deleteUpload(uploadId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: uploadsQueryKey });
      queryClient.invalidateQueries({ queryKey: uploadsQuotaQueryKey });
    },
  });

  const clearMutation = useMutation({
    mutationFn: () => api.clearUploads(),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: uploadsQueryKey });
      queryClient.invalidateQueries({ queryKey: uploadsQuotaQueryKey });
    },
  });

  // Applies the result of attaching an upload the same way MoleculePanel's
  // own handleBuilt does for the 2D-sketcher path (setMolecule/
  // setMoleculeFrames directly from the response) -- a 1/2-geometry
  // upload never goes through a chat turn, so there is no SSE event to
  // pick this up otherwise. A 3+-geometry (geometry_set) attach instead
  // applies its notice message via applyEvent -- idempotent by message id
  // (see chatStore's own dedup), so this is safe even if SSE also delivers
  // the identical event a moment later -- and invalidates the job lists so
  // the new job shows up without waiting for the next poll tick. A blind-
  // input (.inp/.input/.json) attach (P9.6) is the same applyEvent path as
  // geometry_set, minus the job-list invalidation -- nothing was
  // submitted, only a message appended.
  const attachMutation = useMutation({
    mutationFn: (uploadId: string) => api.attachUpload(activeThreadId as string, uploadId),
    onSuccess: (result) => {
      setAttachError(null);
      if (result.kind === "frames" && result.state) {
        setMolecule(result.state.molecule);
        setMoleculeFrames(result.state.molecule_frames);
      } else if (result.kind === "geometry_set") {
        if (result.message) applyEvent({ type: "message", message: result.message });
        queryClient.invalidateQueries({ queryKey: jobsListQueryKey });
        if (activeThreadId) queryClient.invalidateQueries({ queryKey: jobsQueryKey(activeThreadId) });
      } else if (result.kind === "raw_file") {
        if (result.message) applyEvent({ type: "message", message: result.message });
      }
    },
    onError: (err) => setAttachError(String(err)),
  });

  const invalidateUploads = () => {
    queryClient.invalidateQueries({ queryKey: uploadsQueryKey });
    queryClient.invalidateQueries({ queryKey: uploadsQuotaQueryKey });
  };

  const handleDrop = async (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setDragOver(false);
    setDropError(null);
    const files = Array.from(e.dataTransfer.files ?? []);
    const accepted = files.filter((f) => hasAllowedExtension(f.name));
    const rejected = files.filter((f) => !hasAllowedExtension(f.name));
    if (rejected.length > 0) {
      setDropError(`Skipped ${rejected.map((f) => f.name).join(", ")} -- only XYZ, INP, INPUT, and JSON files are supported.`);
    }
    if (accepted.length === 0) return;

    setDropProgress({ done: 0, total: accepted.length });
    const failed: string[] = [];
    for (let i = 0; i < accepted.length; i++) {
      try {
        await api.addUpload(accepted[i]);
      } catch (err) {
        failed.push(`${accepted[i].name}: ${String(err)}`);
      }
      setDropProgress({ done: i + 1, total: accepted.length });
    }
    setDropProgress(null);
    invalidateUploads();
    if (failed.length > 0) setDropError(`Failed to add: ${failed.join("; ")}`);
  };

  const uploads = (uploadsQuery.data ?? []).filter((u) =>
    u.original_name.toLowerCase().includes(search.toLowerCase()),
  );

  return (
    <CollapsibleSection
      title="Files"
      collapsed={collapsed}
      onToggle={() => setCollapsed((c) => !c)}
      headerExtra={
        <button
          onClick={(e) => {
            e.stopPropagation();
            setAdding((a) => !a);
          }}
          className="rounded p-0.5 text-text-muted hover:bg-surface-raised hover:text-text"
          title="Add file"
        >
          {adding ? <X size={13} /> : <Plus size={13} />}
        </button>
      }
      subHeader={<StorageUsageBadge quota={quotaQuery.data} label="Files storage" />}
    >
      <div
        data-testid="files-drop-zone"
        onDragOver={(e) => {
          e.preventDefault();
          setDragOver(true);
        }}
        onDragLeave={() => setDragOver(false)}
        onDrop={handleDrop}
        className={`flex flex-col gap-1.5 px-3 pb-2 ${dragOver ? "rounded bg-accent/10 outline-dashed outline-1 outline-accent" : ""}`}
      >
        {adding && <AddFilesForm onDone={() => setAdding(false)} />}

        <div className="flex items-center gap-1.5 rounded border border-dashed border-border px-2 py-1.5 text-[11px] text-text-muted">
          <FolderDown size={12} />
          Drop an XYZ geometry or a blind ORCA/BAGEL input (.inp/.input/.json) to add it here
        </div>
        {dropProgress && (
          <div className="flex items-center gap-1.5 text-[11px] text-text-muted">
            <Loader2 size={11} className="animate-spin" />
            Uploading {dropProgress.done + 1} of {dropProgress.total}...
          </div>
        )}
        {dropError && <div className="text-[11px] text-status-failed">{dropError}</div>}
        {attachError && <div className="text-[11px] text-status-failed">{attachError}</div>}

        {uploads.length > 0 && (
          <div className="flex items-center gap-1.5 rounded border border-border bg-surface-raised px-2 py-1">
            <Search size={12} className="text-text-muted" />
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search files..."
              className="min-w-0 flex-1 bg-transparent text-xs text-text placeholder:text-text-muted outline-none"
            />
          </div>
        )}

        <div className="flex flex-col">
          {uploads.map((u) => {
            const sniff = sniffLabel(u);
            const isXyz = u.extension === ".xyz";
            const attaching = attachMutation.isPending && attachMutation.variables === u.id;
            return (
              <div key={u.id} className="group flex items-center gap-1.5 py-0.5 text-xs" data-testid="upload-row">
                <button
                  onClick={() => setPreviewUpload(u)}
                  className="min-w-0 flex-1 truncate text-left text-text-muted hover:text-text hover:underline"
                  title={u.original_name}
                >
                  {u.original_name}
                </button>
                {sniff && (
                  <span
                    className="flex shrink-0 items-center gap-0.5 rounded-full bg-surface-raised px-1.5 py-0.5 text-[10px] text-text-muted"
                    title={sniff}
                  >
                    {u.sniff!.kind === "set" && <Layers size={9} />}
                    {sniff}
                  </span>
                )}
                <button
                  onClick={() => attachMutation.mutate(u.id)}
                  disabled={!activeThreadId || attaching}
                  className="shrink-0 rounded p-0.5 text-text-muted opacity-0 hover:text-accent group-hover:opacity-100 disabled:opacity-30"
                  title={
                    activeThreadId
                      ? isXyz
                        ? sniff && u.sniff!.kind === "set"
                          ? "Attach -- creates a geometry set job"
                          : "Attach to conversation"
                        : "Attach -- adds this file's content to the conversation"
                      : "Open a conversation first"
                  }
                  data-testid="upload-attach"
                >
                  {attaching ? <Loader2 size={11} className="animate-spin" /> : <Paperclip size={11} />}
                </button>
                <button
                  onClick={() => deleteMutation.mutate(u.id)}
                  data-testid="upload-delete"
                  className={`shrink-0 rounded p-0.5 hover:text-status-failed group-hover:opacity-100 ${
                    deleteMutation.isError && deleteMutation.variables === u.id
                      ? "text-status-failed opacity-100"
                      : "text-text-muted opacity-0"
                  }`}
                  title={
                    deleteMutation.isError && deleteMutation.variables === u.id
                      ? `Failed to remove: ${String(deleteMutation.error)}`
                      : "Remove"
                  }
                >
                  <Trash2 size={11} />
                </button>
              </div>
            );
          })}
          {uploads.length === 0 && !uploadsQuery.isLoading && (
            <div className="py-1 text-xs text-text-muted">{search ? "No matching files." : "No files yet."}</div>
          )}
        </div>

        {/* Two-click confirm, never a native confirm() dialog -- matching
            this app's standing rule that no destructive action is ever
            one click (see admin/ConfirmButton.tsx's own docstring); a
            small inline variant of that same pattern rather than
            importing an admin-scoped component into an ordinary panel. */}
        {uploads.length > 0 &&
          (clearConfirming ? (
            <div className="flex items-center gap-1.5 text-[11px]" data-testid="files-clear-all-confirm">
              <span className="text-status-failed">Delete all {uploads.length} files?</span>
              <button
                onClick={() => {
                  clearMutation.mutate();
                  setClearConfirming(false);
                }}
                disabled={clearMutation.isPending}
                className="rounded bg-status-failed px-1.5 py-0.5 font-medium text-white disabled:opacity-50"
                data-testid="files-clear-all-confirm-yes"
              >
                {clearMutation.isPending ? "Working..." : "Confirm"}
              </button>
              <button
                onClick={() => setClearConfirming(false)}
                className="rounded border border-border px-1.5 py-0.5 text-text-muted hover:text-text"
              >
                Cancel
              </button>
            </div>
          ) : (
            <button
              onClick={() => setClearConfirming(true)}
              className="self-start text-[11px] text-text-muted underline decoration-dotted hover:text-status-failed"
              data-testid="files-clear-all"
            >
              Clear all
            </button>
          ))}
      </div>
      {previewUpload && <FilePreviewFlyout upload={previewUpload} onClose={() => setPreviewUpload(null)} />}
    </CollapsibleSection>
  );
}

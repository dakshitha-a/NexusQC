import { useEffect, useRef, useState } from "react";
import type { DragEvent, KeyboardEvent } from "react";
import { Trash2, Plus, X, Upload, FolderDown, Link2, Loader2 } from "lucide-react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { CollapsibleSection } from "../app-shell/CollapsibleSection";
import { Flyout } from "../app-shell/Flyout";
import { DownloadButton } from "../app-shell/DownloadButton";
import { SearchableText, type SearchableTextHandle } from "../app-shell/SearchableText";
import { useLayoutStore } from "../lib/layoutStore";
import { triggerDownload } from "../lib/download";
import { StorageUsageBadge } from "../app-shell/StorageUsageBadge";
import { SearchInput, SearchToggle } from "../app-shell/SearchField";
import { kbQuotaQueryKey, kbSourcesQueryKey, useKbQuotaQuery, useKbSourcesQuery } from "../lib/queries";
import * as api from "../lib/api";
import { KB_PAPER_DRAG_TYPE, type DraggablePaper } from "../lib/dragTypes";

function AddSourceForm({ onDone }: { onDone: () => void }) {
  const queryClient = useQueryClient();
  const fileRef = useRef<HTMLInputElement>(null);
  // "paper" first and selected by default -- academic papers are the more
  // common thing a user adds through this form; manuals are mostly
  // pre-seeded (see scripts/seed_knowledge_base.py).
  const [docType, setDocType] = useState<"manual" | "paper">("paper");
  const [fileNames, setFileNames] = useState<string[]>([]);
  const [url, setUrl] = useState("");

  const addMutation = useMutation({
    mutationFn: async (files: File[]) => {
      for (const file of files) {
        await api.addKbSource(file, docType);
      }
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: kbSourcesQueryKey });
      queryClient.invalidateQueries({ queryKey: kbQuotaQueryKey });
      onDone();
    },
  });

  // F-002: a 409 here means the site's robots.txt asks not to be ingested.
  // That is worth showing as a distinct, answerable question ("this site
  // asks not to be crawled -- fetch anyway?") rather than as a generic red
  // error string, since the operator is the one entitled to decide and the
  // only thing standing between them and the answer is one more click.
  const addUrlMutation = useMutation({
    mutationFn: ({ u, ignoreRobots }: { u: string; ignoreRobots: boolean }) =>
      api.addKbSourceUrl(u, docType, ignoreRobots),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: kbSourcesQueryKey });
      queryClient.invalidateQueries({ queryKey: kbQuotaQueryKey });
      onDone();
    },
  });

  const buttonLabel =
    fileNames.length === 0
      ? "Choose PDF/TXT/MD/DOCX files"
      : fileNames.length === 1
        ? fileNames[0]
        : `${fileNames.length} files selected`;

  const submitUrl = () => {
    const trimmed = url.trim();
    if (trimmed && !addUrlMutation.isPending) addUrlMutation.mutate({ u: trimmed, ignoreRobots: false });
  };

  return (
    <div className="flex flex-col gap-2 rounded border border-border bg-surface-raised p-2" data-testid="kb-add-form">
      <div className="flex items-center gap-3 text-xs text-text-muted">
        <label className="flex items-center gap-1">
          <input type="radio" checked={docType === "paper"} onChange={() => setDocType("paper")} />
          paper
        </label>
        <label className="flex items-center gap-1">
          <input type="radio" checked={docType === "manual"} onChange={() => setDocType("manual")} />
          manual
        </label>
      </div>

      <input
        ref={fileRef}
        type="file"
        accept=".pdf,.txt,.md,.docx"
        multiple
        className="hidden"
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
          className="rounded bg-accent px-2 py-1 text-xs text-on-accent disabled:opacity-40"
        >
          {addMutation.isPending ? "Uploading..." : "Add"}
        </button>
      </div>
      {addMutation.isError && <div className="text-xs text-status-failed">{String(addMutation.error)}</div>}

      <div className="flex items-center gap-2 text-3xs uppercase tracking-wide text-text-muted">
        <div className="h-px flex-1 bg-border" />
        or add a web page
        <div className="h-px flex-1 bg-border" />
      </div>

      <div className="flex items-center gap-1.5 rounded border border-border px-2 py-1">
        <Link2 size={12} className="shrink-0 text-text-muted" />
        <input
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          onKeyDown={(e: KeyboardEvent<HTMLInputElement>) => {
            if (e.key === "Enter") submitUrl();
          }}
          placeholder="https://example.com/article"
          className="min-w-0 flex-1 bg-transparent text-xs text-text placeholder:text-text-muted outline-none"
        />
      </div>
      <div className="flex gap-2">
        <button
          onClick={submitUrl}
          disabled={!url.trim() || addUrlMutation.isPending}
          className="rounded bg-accent px-2 py-1 text-xs text-on-accent disabled:opacity-40"
        >
          {addUrlMutation.isPending ? "Fetching..." : "Fetch & add"}
        </button>
        <button onClick={onDone} className="rounded px-2 py-1 text-xs text-text-muted hover:text-text">
          Cancel
        </button>
      </div>
      {addUrlMutation.isError &&
        (addUrlMutation.error instanceof api.ApiError && addUrlMutation.error.status === 409 ? (
          <div
            data-testid="kb-robots-warning"
            className="flex flex-col gap-1.5 rounded border border-status-running/50 bg-status-running/10 p-2 text-xs text-text"
          >
            <div>{addUrlMutation.error.message}</div>
            <button
              onClick={() => addUrlMutation.mutate({ u: url.trim(), ignoreRobots: true })}
              data-testid="kb-robots-override"
              className="self-start rounded border border-border px-2 py-1 text-2xs text-text-muted hover:bg-surface hover:text-text"
            >
              Fetch it anyway
            </button>
          </div>
        ) : (
          <div className="text-xs text-status-failed">{String(addUrlMutation.error)}</div>
        ))}
    </div>
  );
}

// Kept in sync with app/rag/ingest.py's ALLOWED_FILE_EXTENSIONS -- this is
// just a fast client-side check to explain a rejection immediately; the
// backend re-validates regardless, since a drag gesture can carry any file.
const ALLOWED_EXTENSIONS = [".pdf", ".txt", ".md", ".docx"];

function hasAllowedExtension(filename: string): boolean {
  const lower = filename.toLowerCase();
  return ALLOWED_EXTENSIONS.some((ext) => lower.endsWith(ext));
}

// PDF/HTML sources render via native browser handling (PDF.js's own find
// UI, real page layout) -- everything else (the vast majority of KB
// sources: manuals generated as plain text, uploaded .txt/.md/.docx) is
// fetched and rendered through SearchableText instead, so it gets a real
// find bar rather than relying on cross-frame browser find.
function isNativelyRenderedSource(source: string): boolean {
  const lower = source.toLowerCase();
  return lower.endsWith(".pdf") || lower.endsWith(".html") || lower.endsWith(".htm");
}

function KbPreviewFlyout({ source, onClose }: { source: string; onClose: () => void }) {
  const native = isNativelyRenderedSource(source);
  const [text, setText] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const searchRef = useRef<SearchableTextHandle>(null);

  useEffect(() => {
    if (native) return;
    setText(null);
    setError(null);
    fetch(api.kbSourceContentUrl(source))
      .then((r) => api.checkRawResponse(r, "Couldn't load the source"))
      .then((r) => (r.ok ? r.text() : Promise.reject(new Error(`HTTP ${r.status}`))))
      .then(setText)
      .catch((e) => setError(String(e)));
  }, [source, native]);

  return (
    <Flyout
      open
      onClose={onClose}
      title={source}
      widthClassName="w-140"
      headerActions={
        // The URL rather than the `text` state above, deliberately: a
        // natively-rendered source (PDF, HTML) never populates that state --
        // it goes straight into an <iframe> -- and the content route serves
        // both kinds. A KB source is already a real filename with a real
        // extension, so it keeps its own name rather than being restyled.
        <DownloadButton
          title={`Download ${source}`}
          testId="flyout-download-kb-source"
          onDownload={() => triggerDownload(api.kbSourceContentUrl(source), source)}
        />
      }
      onEscapeKeyDown={(e) => {
        if (searchRef.current?.hasQuery()) {
          e.preventDefault();
          searchRef.current.clear();
        }
      }}
    >
      {native ? (
        <iframe
          src={api.kbSourceContentUrl(source)}
          title={source}
          className="h-full w-full rounded border border-border bg-white"
        />
      ) : error ? (
        <div className="text-xs text-status-failed">{error}</div>
      ) : text == null ? (
        <div className="text-xs text-text-muted">Loading...</div>
      ) : (
        <SearchableText ref={searchRef} text={text} />
      )}
    </Flyout>
  );
}

export function KbSection() {
  const { kbCollapsed: collapsed, toggleKb } = useLayoutStore();
  const [search, setSearch] = useState("");
  const [searchOpen, setSearchOpen] = useState(false);
  const [adding, setAdding] = useState(false);
  const [dragOver, setDragOver] = useState(false);
  const [previewSource, setPreviewSource] = useState<string | null>(null);
  const [dropError, setDropError] = useState<string | null>(null);
  // { done, total } while a drag-dropped batch is uploading -- driven by
  // explicit onSettled bookkeeping rather than the mutations' own
  // isPending, since several files/mutate calls can be in flight
  // concurrently and a single useMutation hook only reflects its most
  // recent call.
  const [dropProgress, setDropProgress] = useState<{ done: number; total: number } | null>(null);
  const sourcesQuery = useKbSourcesQuery();
  const quotaQuery = useKbQuotaQuery();
  const queryClient = useQueryClient();

  const deleteMutation = useMutation({
    mutationFn: (source: string) => api.deleteKbSource(source),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: kbSourcesQueryKey });
      queryClient.invalidateQueries({ queryKey: kbQuotaQueryKey });
    },
  });

  const invalidateSources = () => {
    queryClient.invalidateQueries({ queryKey: kbSourcesQueryKey });
    queryClient.invalidateQueries({ queryKey: kbQuotaQueryKey });
  };

  // Sequential (not Promise.all) and plain async/await rather than firing
  // several concurrent useMutation() calls -- with several files in flight
  // at once, per-call progress bookkeeping is otherwise hard to attribute
  // reliably, and sequential uploads also avoid hammering the local
  // embedding pipeline with N concurrent requests.
  const handleDrop = async (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setDragOver(false);
    setDropError(null);
    const paperPayload = e.dataTransfer.getData(KB_PAPER_DRAG_TYPE);
    if (paperPayload) {
      let paper: DraggablePaper;
      try {
        paper = JSON.parse(paperPayload) as DraggablePaper;
      } catch {
        return; // malformed drag payload -- ignore rather than ingest garbage
      }
      setDropProgress({ done: 0, total: 1 });
      try {
        await api.addKbSourceText(paper.block, "paper");
      } catch (err) {
        setDropError(String(err));
      } finally {
        setDropProgress(null);
        invalidateSources();
      }
      return;
    }

    const files = Array.from(e.dataTransfer.files ?? []);
    const accepted = files.filter((f) => hasAllowedExtension(f.name));
    const rejected = files.filter((f) => !hasAllowedExtension(f.name));
    if (rejected.length > 0) {
      setDropError(
        `Skipped ${rejected.map((f) => f.name).join(", ")}: only PDF, TXT, MD and DOCX files are supported.`,
      );
    }
    if (accepted.length === 0) return;

    // Dropped files have no doc_type selector attached to the gesture --
    // default to "paper" (the more common drop case, e.g. a PDF of a
    // journal article); the "+" form's radio lets the user pick "manual"
    // explicitly when that's what they're adding.
    setDropProgress({ done: 0, total: accepted.length });
    const failed: string[] = [];
    for (let i = 0; i < accepted.length; i++) {
      try {
        await api.addKbSource(accepted[i], "paper");
      } catch {
        failed.push(accepted[i].name);
      }
      setDropProgress({ done: i + 1, total: accepted.length });
    }
    setDropProgress(null);
    invalidateSources();
    if (failed.length > 0) setDropError(`Failed to add: ${failed.join(", ")}`);
  };

  const sources = (sourcesQuery.data ?? []).filter((s) =>
    s.source.toLowerCase().includes(search.toLowerCase()),
  );

  return (
    <CollapsibleSection
      title="Knowledge base"
      collapsed={collapsed}
      onToggle={toggleKb}
      stickyHeader
      scrollBody
      className="min-h-0"
      action={{
        icon: <Plus size={14} />,
        activeIcon: <X size={14} />,
        label: "Add source",
        active: adding,
        onActivate: setAdding,
        testId: "kb-add-toggle",
      }}
      headerExtra={
        <div className="flex shrink-0 items-center gap-1">
          <StorageUsageBadge quota={quotaQuery.data} label="Knowledge base storage" />
          <SearchToggle
            active={Boolean(search)}
            open={searchOpen}
            onOpenChange={setSearchOpen}
            label="Search sources"
            testId="kb-search"
          />
        </div>
      }
    >
      <div
        data-testid="kb-drop-zone"
        onDragOver={(e) => {
          e.preventDefault();
          setDragOver(true);
        }}
        onDragLeave={() => setDragOver(false)}
        onDrop={handleDrop}
        className={`flex flex-col gap-1.5 px-3 pb-2 ${dragOver ? "rounded bg-accent/10 outline-dashed outline-1 outline-accent" : ""}`}
      >
        {adding && <AddSourceForm onDone={() => setAdding(false)} />}

        <div className="flex items-center gap-1.5 rounded border border-dashed border-border px-2 py-1.5 text-2xs text-text-muted">
          <FolderDown size={12} />
          Drop a PDF/TXT/MD/DOCX file, or a paper card from chat, to add it here
        </div>
        {dropProgress && (
          <div className="flex items-center gap-1.5 text-2xs text-text-muted">
            <Loader2 size={11} className="animate-spin" />
            Uploading {dropProgress.done + 1} of {dropProgress.total}...
          </div>
        )}
        {dropError && <div className="text-2xs text-status-failed">{dropError}</div>}

        {searchOpen && (
          <SearchInput
            value={search}
            onChange={setSearch}
            onClose={() => setSearchOpen(false)}
            placeholder="Search sources"
            testId="kb-search"
          />
        )}

        <div className="flex flex-col">
          {sources.map((s) => (
            <div key={s.source} className="group flex items-center gap-1.5 py-0.5 text-xs">
              <button
                onClick={() => setPreviewSource(s.source)}
                className="min-w-0 flex-1 truncate text-left text-text-muted hover:text-text hover:underline"
                title={s.source}
              >
                {s.source}
              </button>
              <span className="shrink-0 text-3xs text-text-muted">
                {s.doc_type} · {s.n_chunks}
              </span>
              <button
                onClick={() => deleteMutation.mutate(s.source)}
                className={`shrink-0 rounded p-0.5 hover:text-status-failed group-hover:opacity-100 ${
                  deleteMutation.isError && deleteMutation.variables === s.source
                    ? "text-status-failed opacity-100"
                    : "text-text-muted opacity-0"
                }`}
                title={
                  deleteMutation.isError && deleteMutation.variables === s.source
                    ? `Failed to remove: ${String(deleteMutation.error)}`
                    : "Remove"
                }
              >
                <Trash2 size={11} />
              </button>
            </div>
          ))}
          {sources.length === 0 && !sourcesQuery.isLoading && (
            <div className="py-1 text-xs text-text-muted">
              {search ? "No matching sources." : "No sources yet."}
            </div>
          )}
        </div>
      </div>
      {previewSource && <KbPreviewFlyout source={previewSource} onClose={() => setPreviewSource(null)} />}
    </CollapsibleSection>
  );
}

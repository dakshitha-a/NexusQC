import { useRef, useState } from "react";
import { Search, Trash2, Plus, X, Upload } from "lucide-react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { CollapsibleSection } from "../app-shell/CollapsibleSection";
import { kbSourcesQueryKey, useKbSourcesQuery } from "../lib/queries";
import * as api from "../lib/api";

function AddSourceForm({ onDone }: { onDone: () => void }) {
  const queryClient = useQueryClient();
  const fileRef = useRef<HTMLInputElement>(null);
  const [docType, setDocType] = useState<"manual" | "paper">("manual");
  const [fileName, setFileName] = useState<string | null>(null);

  const addMutation = useMutation({
    mutationFn: (file: File) => api.addKbSource(file, docType),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: kbSourcesQueryKey });
      onDone();
    },
  });

  return (
    <div className="flex flex-col gap-2 rounded border border-border bg-surface-raised p-2">
      <input
        ref={fileRef}
        type="file"
        accept=".pdf,.txt,.md"
        className="hidden"
        onChange={(e) => setFileName(e.target.files?.[0]?.name ?? null)}
      />
      <button
        onClick={() => fileRef.current?.click()}
        className="flex items-center gap-1.5 rounded border border-dashed border-border px-2 py-1.5 text-xs text-text-muted hover:border-accent hover:text-text"
      >
        <Upload size={12} />
        {fileName ?? "Choose a PDF/TXT/MD file"}
      </button>
      <div className="flex items-center gap-3 text-xs text-text-muted">
        <label className="flex items-center gap-1">
          <input type="radio" checked={docType === "manual"} onChange={() => setDocType("manual")} />
          manual
        </label>
        <label className="flex items-center gap-1">
          <input type="radio" checked={docType === "paper"} onChange={() => setDocType("paper")} />
          paper
        </label>
      </div>
      <div className="flex gap-2">
        <button
          onClick={() => fileRef.current?.files?.[0] && addMutation.mutate(fileRef.current.files[0])}
          disabled={!fileName || addMutation.isPending}
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

export function KbSection() {
  const [collapsed, setCollapsed] = useState(false);
  const [search, setSearch] = useState("");
  const [adding, setAdding] = useState(false);
  const sourcesQuery = useKbSourcesQuery();
  const queryClient = useQueryClient();

  const deleteMutation = useMutation({
    mutationFn: (source: string) => api.deleteKbSource(source),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: kbSourcesQueryKey }),
  });

  const sources = (sourcesQuery.data ?? []).filter((s) =>
    s.source.toLowerCase().includes(search.toLowerCase()),
  );

  return (
    <CollapsibleSection
      title="Knowledge base"
      collapsed={collapsed}
      onToggle={() => setCollapsed((c) => !c)}
      headerExtra={
        <button
          onClick={(e) => {
            e.stopPropagation();
            setAdding((a) => !a);
          }}
          className="rounded p-0.5 text-text-muted hover:bg-surface-raised hover:text-text"
          title="Add source"
        >
          {adding ? <X size={13} /> : <Plus size={13} />}
        </button>
      }
    >
      <div className="flex flex-col gap-1.5 px-3 pb-2">
        {adding && <AddSourceForm onDone={() => setAdding(false)} />}

        <div className="flex items-center gap-1.5 rounded border border-border bg-surface-raised px-2 py-1">
          <Search size={12} className="text-text-muted" />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search sources..."
            className="min-w-0 flex-1 bg-transparent text-xs text-text placeholder:text-text-muted outline-none"
          />
        </div>

        <div className="flex flex-col">
          {sources.map((s) => (
            <div key={s.source} className="group flex items-center gap-1.5 py-0.5 text-xs">
              <div className="min-w-0 flex-1 truncate text-text-muted" title={s.source}>
                {s.source}
              </div>
              <span className="shrink-0 text-[10px] text-text-muted">
                {s.doc_type} · {s.n_chunks}
              </span>
              <button
                onClick={() => deleteMutation.mutate(s.source)}
                className="shrink-0 rounded p-0.5 text-text-muted opacity-0 hover:text-status-failed group-hover:opacity-100"
                title="Remove"
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
    </CollapsibleSection>
  );
}

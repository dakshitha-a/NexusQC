import { useState } from "react";
import { BookPlus, Check, ExternalLink } from "lucide-react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import * as api from "../lib/api";
import { kbSourcesQueryKey } from "../lib/queries";
import { KB_PAPER_DRAG_TYPE, type DraggablePaper } from "../lib/dragTypes";

// One paper block from a search_academic_literature tool result, rendered
// as a distinct card instead of one opaque text blob -- so the user can
// add a single paper to the knowledge base without pulling in the whole
// tool result. Splitting/parsing happens in the caller (ToolResultChip);
// this component just displays one already-split block and offers ways to
// get its text into the KB (a button, the literal ask, plus drag-and-drop
// as a bonus affordance since dragging a small card onto a side panel is
// inherently a bit fiddly).
export function PaperCard({ block }: { block: string }) {
  const [added, setAdded] = useState(false);
  const queryClient = useQueryClient();
  const lines = block.split("\n");
  const title = lines[0] ?? "Untitled";
  const urlLine = lines.find((l) => l.startsWith("URL:"));
  const url = urlLine?.slice("URL:".length).trim();

  const addMutation = useMutation({
    mutationFn: () => api.addKbSourceText(block, "paper"),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: kbSourcesQueryKey });
      setAdded(true);
    },
  });

  const dragPayload: DraggablePaper = { title, block };

  return (
    <div
      draggable
      onDragStart={(e) => {
        e.dataTransfer.setData(KB_PAPER_DRAG_TYPE, JSON.stringify(dragPayload));
        e.dataTransfer.effectAllowed = "copy";
      }}
      className="cursor-grab rounded border border-border bg-surface-raised p-2 text-xs active:cursor-grabbing"
      title="Drag onto the Knowledge base panel, or use the button, to add this paper"
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0 flex-1">
          <div className="font-medium text-text">{title}</div>
          {url && (
            <a
              href={url}
              target="_blank"
              rel="noreferrer"
              onClick={(e) => e.stopPropagation()}
              className="mt-0.5 inline-flex items-center gap-1 text-2xs text-text-muted hover:text-accent hover:underline"
            >
              <ExternalLink size={10} />
              {url}
            </a>
          )}
        </div>
        <button
          onClick={() => addMutation.mutate()}
          disabled={addMutation.isPending || added}
          className="flex shrink-0 items-center gap-1 rounded bg-accent px-1.5 py-1 text-2xs text-on-accent disabled:opacity-50"
          title="Add this paper to the knowledge base"
        >
          {added ? <Check size={11} /> : <BookPlus size={11} />}
          {added ? "Added" : addMutation.isPending ? "Adding..." : "Add to KB"}
        </button>
      </div>
      {addMutation.isError && <div className="mt-1 text-status-failed">{String(addMutation.error)}</div>}
    </div>
  );
}

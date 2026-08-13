// Custom drag-and-drop MIME type for dragging a single paper (from a
// search_academic_literature chat result) onto the knowledge-base
// drop-zone. Shared between the drag source (PaperCard) and the drop
// target (KbSection) so they can't drift out of sync.
export const KB_PAPER_DRAG_TYPE = "application/x-kb-paper";

export interface DraggablePaper {
  title: string;
  block: string; // full block text, verbatim, as returned by search_academic_literature
}

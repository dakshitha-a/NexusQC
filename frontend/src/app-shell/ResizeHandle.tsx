import { useRef } from "react";

interface ResizeHandleProps {
  width: number;
  onResize: (width: number) => void;
  min: number;
  max: number;
  // +1 for a handle on a panel's right edge (dragging right grows it),
  // -1 for a handle on a panel's left edge (dragging right shrinks it).
  direction: 1 | -1;
  label: string;
  /** The current text scale. Panel widths are stored in design pixels and
   *  rendered as rem so they grow with the text (a 288px sidebar at the
   *  largest text size fits about as many characters as a 213px one does at
   *  the smallest, which is not a sidebar any more). A pointer, though, moves
   *  in real screen pixels, so the drag delta is divided by the scale before
   *  it reaches the stored width -- otherwise dragging at 1.35 would move the
   *  edge a third further than the pointer went. */
  scale?: number;
}

// A draggable divider between two of the three fixed shell regions
// (LeftRail/ChatPane/RightDock). Pointer capture is used instead of
// window-level mousemove/mouseup listeners so dragging keeps working even
// if the pointer briefly leaves the 12px hit area -- no cleanup-on-unmount
// needed since the events are scoped to this element via the captured
// pointer id, not the window.
export function ResizeHandle({ width, onResize, min, max, direction, label, scale = 1 }: ResizeHandleProps) {
  const dragStart = useRef<{ x: number; width: number } | null>(null);

  const step = (delta: number) => {
    onResize(Math.min(max, Math.max(min, width + delta * direction)));
  };

  return (
    <div
      role="separator"
      aria-orientation="vertical"
      aria-label={`Resize ${label}`}
      aria-valuemin={min}
      aria-valuemax={max}
      aria-valuenow={Math.round(width)}
      tabIndex={0}
      onPointerDown={(e) => {
        e.currentTarget.setPointerCapture(e.pointerId);
        dragStart.current = { x: e.clientX, width };
      }}
      onPointerMove={(e) => {
        if (!dragStart.current) return;
        const delta = ((e.clientX - dragStart.current.x) * direction) / scale;
        onResize(Math.min(max, Math.max(min, dragStart.current.width + delta)));
      }}
      onPointerUp={(e) => {
        dragStart.current = null;
        e.currentTarget.releasePointerCapture(e.pointerId);
      }}
      onKeyDown={(e) => {
        if (e.key === "ArrowLeft") step(-16);
        else if (e.key === "ArrowRight") step(16);
      }}
      className="group relative flex w-3 shrink-0 cursor-col-resize touch-none items-stretch justify-center select-none"
    >
      <div className="w-px bg-border transition-colors group-hover:bg-accent group-active:bg-accent" />
    </div>
  );
}

import { useCallback, useEffect, useRef, useState } from "react";

/**
 * A scrollbar, used as a frame scrubber.
 *
 * ## Why not `<input type="range">`
 *
 * Two reasons, and the second is the interesting one.
 *
 * A native range input renders its own chrome, which no amount of palette
 * discipline elsewhere affects: on a dark surface Chrome draws a bright,
 * chunky thumb on a light track, and it reads as the loudest thing on the
 * panel while being one of the least important. Everything else in this app
 * is quiet by default and gets louder only to mean something.
 *
 * More usefully: a range input's thumb is a fixed size, so it says nothing
 * about how much it is scrolling through. A scrollbar's does -- its thumb is
 * the fraction of the content currently in view, which is why a long document
 * has a short thumb. Applying that here means the thumb width IS the frame
 * count: a 3-frame scan gets a third of the track, a 200-frame trajectory gets
 * a sliver. You can tell how long a series is before touching it, and the
 * control matches the scrollbars everywhere else in the app
 * (`::-webkit-scrollbar-thumb` in index.css: `--border`, rounded, transparent
 * track).
 *
 * The floor exists because the honest width becomes ungrabbable: at 200 frames
 * a true 0.5% thumb is under a pixel on a 280px dock. Below the floor the
 * thumb stops shrinking and the proportion stops being literal -- but by then
 * "very many frames" is the only message left to convey, and it still conveys
 * it.
 */
const MIN_THUMB_PCT = 7;

export function FrameScrubber({
  index,
  count,
  onChange,
  noun = "Frame",
}: {
  index: number;
  count: number;
  onChange: (next: number) => void;
  noun?: string;
}) {
  const trackRef = useRef<HTMLDivElement>(null);
  const [dragging, setDragging] = useState(false);

  const thumbPct = Math.max(100 / count, MIN_THUMB_PCT);
  // The thumb travels the track MINUS its own width, so its right edge lands
  // exactly on the end bound at the last frame rather than overhanging it.
  const travelPct = 100 - thumbPct;
  const leftPct = count > 1 ? (index / (count - 1)) * travelPct : 0;

  /** Pointer x -> frame index. Measures against the thumb's travel, not the
   *  raw track width, so the frame under the cursor is the one that ends up
   *  selected rather than one offset by half a thumb. */
  const indexAt = useCallback(
    (clientX: number) => {
      const el = trackRef.current;
      if (!el || count < 2) return 0;
      const rect = el.getBoundingClientRect();
      const thumbPx = (thumbPct / 100) * rect.width;
      const travelPx = rect.width - thumbPx;
      if (travelPx <= 0) return 0;
      const fraction = (clientX - rect.left - thumbPx / 2) / travelPx;
      return Math.max(0, Math.min(count - 1, Math.round(fraction * (count - 1))));
    },
    [count, thumbPct],
  );

  // Bound to the window, not the element: a drag that leaves the track (very
  // easy on a 10px-tall control) must keep scrubbing and must still end on
  // mouseup, which an element-scoped listener would miss entirely.
  useEffect(() => {
    if (!dragging) return;
    const move = (e: PointerEvent) => onChange(indexAt(e.clientX));
    const up = () => setDragging(false);
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
    window.addEventListener("pointercancel", up);
    return () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
      window.removeEventListener("pointercancel", up);
    };
  }, [dragging, indexAt, onChange]);

  if (count < 2) return null;

  return (
    <div
      role="slider"
      tabIndex={0}
      aria-label={`${noun} position`}
      aria-valuemin={1}
      aria-valuemax={count}
      aria-valuenow={index + 1}
      aria-valuetext={`${noun} ${index + 1} of ${count}`}
      data-testid="frame-scrubber"
      onKeyDown={(e) => {
        if (e.key === "ArrowLeft") { e.preventDefault(); onChange(Math.max(0, index - 1)); }
        else if (e.key === "ArrowRight") { e.preventDefault(); onChange(Math.min(count - 1, index + 1)); }
        else if (e.key === "Home") { e.preventDefault(); onChange(0); }
        else if (e.key === "End") { e.preventDefault(); onChange(count - 1); }
      }}
      onPointerDown={(e) => {
        // Clicking anywhere on the track jumps there, same as a scrollbar,
        // and continues straight into a drag without a second gesture.
        e.preventDefault();
        onChange(indexAt(e.clientX));
        setDragging(true);
      }}
      className="group relative flex h-3 w-full cursor-pointer items-center rounded outline-none focus-visible:ring-1 focus-visible:ring-accent"
    >
      {/* The bounds, and they have to be legible: without them the track fades
          into the panel and the series has no visible extent -- you can see
          where the thumb is but not where the end is, which is most of what a
          scrubber is for. Deliberately brighter than the track and the same
          weight as the thumb, so the control reads as a measured span rather
          than a line with something on it. */}
      <span aria-hidden className="absolute left-0 h-3 w-0.5 rounded-full bg-text-muted/35" />
      <span aria-hidden className="absolute right-0 h-3 w-0.5 rounded-full bg-text-muted/35" />

      {/* Track: quiet, and quieter than the thumb, matching the app's own
          scrollbars (transparent track, --border thumb). */}
      <div ref={trackRef} className="relative h-1 w-full rounded-full bg-border/40">
        <div
          aria-hidden
          data-testid="frame-scrubber-thumb"
          style={{ width: `${thumbPct}%`, left: `${leftPct}%` }}
          // The thumb is the brightest thing here, and the bounds are dimmer
          // than it. Reversing that -- which the first pass did -- makes the
          // static furniture out-shout the one part you actually grab, and at
          // a glance you see the extent of the series but not your place in it.
          className={`absolute top-1/2 h-1.5 -translate-y-1/2 rounded-full transition-colors ${
            dragging ? "bg-accent" : "bg-text-muted/70 group-hover:bg-text-muted"
          }`}
        />
      </div>
    </div>
  );
}

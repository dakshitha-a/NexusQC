import { ChevronLeft, ChevronRight, Pause, Play } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { FrameScrubber } from "./FrameScrubber";

/**
 * Navigation for a multi-frame series -- a scan path, an NEB path, a Wigner
 * ensemble, or the molecule panel's own frame history.
 *
 * Four call sites had each grown their own bare `<input type="range">` with a
 * `n/N` caption beside it. A raw slider is a poor fit for this data: at 17
 * frames one pixel of travel is a whole frame, so landing on a *particular*
 * image -- which is the usual reason to touch it at all, e.g. "show me the
 * saddle point" -- is fiddly, and there is no way to play the path through as
 * the animation it represents.
 *
 * So: explicit prev/next for exact steps, a play/pause that walks the series,
 * arrow keys while focused, and a scrubber underneath for coarse jumps in a
 * long series -- see FrameScrubber, which is shaped like this app's scrollbars
 * and sizes its thumb by the frame count. `label` is the caller's own
 * per-frame text (an NEB image name, a scan energy) and is shown alongside the
 * count rather than replacing it -- every caller had one and half of them had
 * dropped the count to make room.
 */
export function FrameStepper({
  index,
  count,
  onChange,
  label,
  noun = "Frame",
  intervalMs = 400,
}: {
  index: number;
  count: number;
  onChange: (next: number) => void;
  /** Per-frame caption, e.g. "Image 3" or "-76.402100 Eh". */
  label?: string;
  /** What one item is called -- "Frame" for a path, "Sample" for an ensemble. */
  noun?: string;
  intervalMs?: number;
}) {
  const [playing, setPlaying] = useState(false);
  // The interval closure must not capture a stale `index`, and re-creating the
  // timer on every frame change would make its period jitter. A ref keeps the
  // timer stable while still reading the current position.
  const indexRef = useRef(index);
  indexRef.current = index;

  useEffect(() => {
    if (!playing || count < 2) return;
    const id = setInterval(() => {
      const next = indexRef.current + 1;
      if (next >= count) {
        // Stops at the end rather than looping: these are paths with a
        // direction (reactant to product, scan start to finish), and a looping
        // animation makes it impossible to tell where the series actually ends.
        setPlaying(false);
        return;
      }
      onChange(next);
    }, intervalMs);
    return () => clearInterval(id);
  }, [playing, count, intervalMs, onChange]);

  // Playing to the end leaves the button showing "play" at the last frame,
  // where pressing it would do nothing; restart from the beginning instead.
  const togglePlay = () => {
    if (!playing && index >= count - 1) onChange(0);
    setPlaying((p) => !p);
  };

  const go = (next: number) => {
    setPlaying(false);
    onChange(Math.max(0, Math.min(count - 1, next)));
  };

  if (count < 2) return null;

  return (
    // Keyboard handling lives on the scrubber below, which is the element with
    // role="slider" -- a screen reader should find the arrow keys on the thing
    // that announces a value, not on an anonymous wrapper.
    <div data-testid="frame-stepper" className="flex flex-col gap-1">
      <div className="flex items-center gap-1.5 text-3xs text-text-muted">
        <button
          onClick={() => go(index - 1)}
          disabled={index <= 0}
          data-testid="frame-prev"
          title={`Previous ${noun.toLowerCase()} (left arrow)`}
          className="rounded p-0.5 hover:bg-surface-raised hover:text-text disabled:opacity-25 disabled:hover:bg-transparent"
        >
          <ChevronLeft size={14} />
        </button>
        <button
          onClick={() => go(index + 1)}
          disabled={index >= count - 1}
          data-testid="frame-next"
          title={`Next ${noun.toLowerCase()} (right arrow)`}
          className="rounded p-0.5 hover:bg-surface-raised hover:text-text disabled:opacity-25 disabled:hover:bg-transparent"
        >
          <ChevronRight size={14} />
        </button>
        <button
          onClick={togglePlay}
          data-testid="frame-play"
          title={playing ? "Pause" : `Play through every ${noun.toLowerCase()}`}
          className="rounded p-0.5 hover:bg-surface-raised hover:text-text"
        >
          {playing ? <Pause size={13} /> : <Play size={13} />}
        </button>
        <span className="ml-1 font-mono tabular-nums text-text">
          {noun} {index + 1} / {count}
        </span>
        {label && <span className="min-w-0 truncate font-mono text-text-muted" title={label}>· {label}</span>}
      </div>
      <FrameScrubber index={index} count={count} onChange={go} noun={noun} />
    </div>
  );
}

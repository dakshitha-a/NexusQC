import { Hash } from "lucide-react";
import { useViewerPrefsStore } from "../lib/viewerPrefsStore";

/**
 * Turns the atom numbers on and off in every 3D viewer at once.
 *
 * Reads and writes the store directly rather than taking value/onChange
 * props, which is what lets it be dropped into a viewer's control overlay
 * without threading state down through the four frame viewers that embed
 * MoleculeViewer. Several of these render at the same time -- the molecule
 * panel's header and the overlay of whatever viewers are open -- and they
 * all show the same state and flip it together.
 *
 * `role="switch"` because that is what it is. It is the first one in this
 * codebase; the alternative was a bare checkbox, which reads to a screen
 * reader as a form field rather than as a control that changes the view.
 */
export function AtomLabelToggle({
  testId,
  className = "",
}: {
  // Required, not defaulted: more than one of these is on screen at a time,
  // so a shared id would make a spec's locator ambiguous.
  testId: string;
  className?: string;
}) {
  const atomLabels = useViewerPrefsStore((s) => s.atomLabels);
  const toggleAtomLabels = useViewerPrefsStore((s) => s.toggleAtomLabels);
  return (
    <button
      onClick={toggleAtomLabels}
      role="switch"
      aria-checked={atomLabels}
      data-testid={testId}
      title={atomLabels ? "Hide atom numbers (every viewer)" : "Show atom numbers (every viewer)"}
      className={`rounded p-1 hover:bg-surface-raised hover:text-text ${
        atomLabels ? "text-accent" : "text-text-muted"
      } ${className}`}
    >
      <Hash size={13} />
    </button>
  );
}

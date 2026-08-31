import { useRef, useState } from "react";
import * as Dialog from "@radix-ui/react-dialog";
import { AlertTriangle } from "lucide-react";
import type { ProjectRow } from "../lib/api";

/**
 * Deleting a project asks which of two genuinely different things the user
 * means, every time, with neither preselected.
 *
 * The ambiguity is real rather than pedantic. "Delete this project" can
 * mean "I am done with this grouping, put the jobs back" or "this whole
 * study was a dead end, take the results too", and guessing wrong in the
 * second direction is unrecoverable. So there is no default and no primary
 * button: both options are laid out with equal weight, and the destructive
 * one is additionally gated on typing the project's own name.
 *
 * Typing the NAME rather than a fixed phrase like DangerZoneSection's
 * PurgeAction does is the one deliberate difference from that component.
 * PurgeAction guards a single deployment-wide action where any phrase is
 * as good as another; here there may be a dozen projects on screen, and
 * the thing worth confirming is WHICH one is about to lose its results.
 */
export function ProjectDeleteDialog({
  project, open, onClose, onConfirm, pending, error,
}: {
  project: ProjectRow;
  open: boolean;
  onClose: () => void;
  onConfirm: (deleteJobs: boolean) => void;
  pending: boolean;
  error: string | null;
}) {
  const [typed, setTyped] = useState("");
  const contentRef = useRef<HTMLDivElement>(null);
  const armed = typed.trim() === project.name.trim();
  const n = project.job_count;
  const jobsWord = `${n} job${n === 1 ? "" : "s"}`;

  return (
    <Dialog.Root open={open} onOpenChange={(o) => !o && onClose()}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-40 bg-black/50 data-[state=open]:animate-fade-in" />
        <Dialog.Content
          ref={contentRef}
          tabIndex={-1}
          // Radix focuses the first focusable child on open, which here is
          // "Delete the project only". That is the safe option, but it is
          // still a default answer: Enter would take it, and this dialog
          // exists precisely because neither answer should be the one that
          // happens by reflex. Focus goes to the dialog itself instead, so
          // the first key press does nothing and the choice has to be made.
          onOpenAutoFocus={(e) => {
            e.preventDefault();
            contentRef.current?.focus();
          }}
          data-testid="project-delete-dialog"
          className="fixed left-1/2 top-1/2 z-50 w-[26rem] max-w-[92vw] -translate-x-1/2 -translate-y-1/2 rounded-lg border border-border bg-surface p-4 shadow-2xl"
        >
          <Dialog.Title className="text-sm font-semibold text-text">Delete "{project.name}"</Dialog.Title>
          <Dialog.Description className="mt-1 text-xs text-text-muted">
            This project holds {jobsWord}. Choose what happens to them.
          </Dialog.Description>

          <div className="mt-3 flex flex-col gap-2">
            <button
              onClick={() => onConfirm(false)}
              disabled={pending}
              data-testid="project-delete-keep-jobs"
              className="rounded border border-border px-3 py-2 text-left hover:bg-surface-raised disabled:opacity-50"
            >
              <div className="text-xs font-medium text-text">Delete the project only</div>
              <div className="mt-0.5 text-[11px] text-text-muted">
                The grouping goes and {n === 1 ? "the job returns" : "the jobs return"} to the job manager.
                Nothing is removed from disk.
              </div>
            </button>

            <div className="rounded border border-status-failed/30 bg-status-failed/[0.03] px-3 py-2">
              <div className="flex items-start gap-2">
                <AlertTriangle size={13} className="mt-0.5 shrink-0 text-status-failed" />
                <div className="min-w-0 flex-1">
                  <div className="text-xs font-medium text-status-failed">
                    Delete the project and its {jobsWord}
                  </div>
                  <div className="mt-0.5 text-[11px] text-text-muted">
                    Every result, output file and orbital in {n === 1 ? "it" : "them"} is deleted. Anything
                    still running is stopped first. There is no undo.
                  </div>
                  <div className="mt-2 flex items-center gap-2">
                    <input
                      value={typed}
                      onChange={(e) => setTyped(e.target.value)}
                      placeholder={project.name}
                      aria-label={`Type ${project.name} to enable`}
                      data-testid="project-delete-phrase"
                      className="min-w-0 flex-1 rounded border border-border bg-bg px-2 py-1 font-mono text-[11px] text-text placeholder:text-text-muted/40 focus:border-status-failed focus:outline-none"
                    />
                    <button
                      onClick={() => onConfirm(true)}
                      disabled={!armed || pending}
                      data-testid="project-delete-with-jobs"
                      className="shrink-0 rounded bg-status-failed px-3 py-1 text-[11px] font-medium text-white disabled:cursor-not-allowed disabled:opacity-25"
                    >
                      {pending ? "Deleting..." : "Delete both"}
                    </button>
                  </div>
                </div>
              </div>
            </div>
          </div>

          {error && (
            <div data-testid="project-delete-error" className="mt-2 text-[11px] text-status-failed">
              {error}
            </div>
          )}
          <div className="mt-3 flex justify-end">
            <button
              onClick={onClose}
              data-testid="project-delete-cancel"
              className="rounded px-3 py-1 text-xs text-text-muted hover:text-text"
            >
              Cancel
            </button>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

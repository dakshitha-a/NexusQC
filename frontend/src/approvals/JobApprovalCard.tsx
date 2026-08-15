import { useState } from "react";
import { ChevronDown, ChevronRight, RotateCcw } from "lucide-react";
import { useMutation } from "@tanstack/react-query";
import * as api from "../lib/api";
import type { PendingApproval } from "../lib/api";
import { useChatStore } from "../lib/chatStore";

const EDITABLE_ENGINES = new Set(["orca", "bagel"]);

export function JobApprovalCard({ pending, threadId }: { pending: PendingApproval; threadId: string }) {
  const engine = pending.engine as string;
  const editable = EDITABLE_ENGINES.has(engine);
  const originalInput = (pending.input_preview as string) ?? "";
  const [inputText, setInputText] = useState(originalInput);
  const [kbOpen, setKbOpen] = useState(false);
  const edited = editable && inputText !== originalInput;

  const approveMutation = useMutation({
    // Only send input_text when the user actually changed it -- sending it
    // unconditionally whenever the engine is editable made every unedited
    // ORCA/BAGEL approval look like a hand-edit server-side (submit_job
    // treats a non-null input_text as "use this verbatim, byte-identical,
    // as the raw input"). That was harmless when the displayed preview
    // happened to equal the real input file, but broke pes_scan jobs: the
    // approval card's preview there is prefixed with a display-only
    // "[Preview of image 1 of N ...]" annotation that isn't valid ORCA/
    // BAGEL syntax, and it was landing in image 0's actual input.inp as a
    // result -- confirmed via a real failed ORCA CASSCF scan job.
    mutationFn: (approved: boolean) => api.approveJob(threadId, approved, edited ? inputText : null),
    // Hide the card the instant the button is clicked instead of waiting
    // on resume_turn's response (a full graph resume + follow-up LLM
    // turn, easily a few seconds) -- see dismissPendingApproval's
    // docstring. On failure, restore the card and surface the error via
    // the same banner handleSend/handleStop use, since this card (and
    // its own inline error display) no longer exists to show it.
    onMutate: () => ({ previous: useChatStore.getState().dismissPendingApproval() }),
    onError: (err, _approved, context) => {
      useChatStore.setState({ pendingApproval: context?.previous ?? null, turnInProgress: false });
      useChatStore.getState().applyEvent({ type: "error", message: String(err) });
    },
  });

  const params = (pending.params as Record<string, unknown>) ?? {};
  const kbContext = pending.kb_context as string | undefined;
  const retryNote = pending.retry_note as string | undefined;
  const scanNote = pending.scan_note as string | undefined;
  const paramCorrections = (pending.param_corrections as string[] | undefined) ?? [];
  const inputWarnings = (pending.input_warnings as string[] | undefined) ?? [];

  return (
    <div className="flex justify-start">
      <div className="w-full max-w-[85%] rounded-lg border border-accent/40 bg-surface p-3.5 text-sm">
        <div className="mb-2 flex items-center justify-between">
          <div className="font-medium text-text">
            Approve {pending.job_type as string} job — {(pending.molecule_name as string) ?? "molecule"}
          </div>
          <span className="rounded bg-surface-raised px-1.5 py-0.5 font-mono text-[10.5px] text-text-muted">
            {engine}
          </span>
        </div>

        {retryNote && (
          <div className="mb-2 rounded border border-status-running/40 bg-status-running/10 px-2 py-1 text-xs text-status-running">
            {retryNote}
          </div>
        )}

        {paramCorrections.length > 0 && (
          <div className="mb-2 rounded border border-accent/40 bg-accent-muted px-2 py-1 text-xs text-accent">
            {paramCorrections.map((note, i) => (
              <div key={i}>Auto-corrected: {note}</div>
            ))}
          </div>
        )}

        <div className="mb-2 text-xs text-text-muted">
          {Object.entries(params)
            .filter(([k]) => !k.startsWith("_"))
            .map(([k, v]) => `${k}=${JSON.stringify(v)}`)
            .join(", ")}
        </div>

        {inputWarnings.length > 0 && (
          <div className="mb-2 rounded border border-status-failed/40 bg-status-failed/10 px-2 py-1 text-xs text-status-failed">
            <div className="font-medium">Structural check found possible issues (not blocking):</div>
            {inputWarnings.map((w, i) => (
              <div key={i}>- {w}</div>
            ))}
          </div>
        )}

        {scanNote && <div className="mb-2 text-[11px] italic text-text-muted">{scanNote}</div>}

        {editable ? (
          <textarea
            value={inputText}
            onChange={(e) => setInputText(e.target.value)}
            rows={10}
            className="mb-2 w-full resize-y rounded border border-border bg-bg p-2 font-mono text-[11.5px] text-text outline-none focus:border-accent"
          />
        ) : (
          <pre className="mb-2 max-h-64 overflow-y-auto rounded border border-border bg-bg p-2 font-mono text-[11.5px] text-text-muted">
            {originalInput}
          </pre>
        )}
        {!editable && (
          <div className="mb-2 text-[11px] text-text-muted">
            PySCF has no literal input file to hand-edit — this preview is a synthetic driver script.
          </div>
        )}

        {kbContext && (
          <div className="mb-2">
            <button
              onClick={() => setKbOpen((o) => !o)}
              className="flex items-center gap-1 text-[11px] text-text-muted hover:text-text"
            >
              {kbOpen ? <ChevronDown size={11} /> : <ChevronRight size={11} />}
              Manual/reference excerpts consulted
            </button>
            {kbOpen && (
              <pre className="mt-1 max-h-48 overflow-y-auto whitespace-pre-wrap rounded border border-border bg-bg p-2 text-[11px] text-text-muted">
                {kbContext}
              </pre>
            )}
          </div>
        )}

        <div className="flex items-center gap-2">
          <button
            onClick={() => approveMutation.mutate(true)}
            className="rounded bg-accent px-3 py-1.5 text-xs font-medium text-white"
          >
            {edited ? "Run edited" : "Approve & run"}
          </button>
          <button
            onClick={() => approveMutation.mutate(false)}
            className="rounded border border-border px-3 py-1.5 text-xs text-text-muted hover:text-text"
          >
            Reject
          </button>
          {edited && (
            <button
              onClick={() => setInputText(originalInput)}
              className="flex items-center gap-1 text-[11px] text-text-muted hover:text-text"
            >
              <RotateCcw size={11} />
              Reset to generated
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

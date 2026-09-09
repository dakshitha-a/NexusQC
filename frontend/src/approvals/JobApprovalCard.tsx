import { useState } from "react";
import { AlertTriangle, ChevronDown, ChevronRight, RotateCcw } from "lucide-react";
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
      // A 400 from the route's pre-resume validation (F-023) means the
      // interrupt was NEVER spent, so restoring the card genuinely puts the
      // user back where they were -- edit the text, click again. The
      // message goes into the store rather than this component's own
      // mutation state because dismissPendingApproval already unmounted
      // this copy of the card; the restored one is a fresh mount with no
      // memory of the failed attempt.
      const message = err instanceof Error ? err.message : String(err);
      const isValidation = err instanceof api.ApiError && err.status === 400;
      // A 409 means the interrupt is definitively GONE -- already answered,
      // or consumed by a resume that has since finished. Restoring the card
      // there was a trap with no way out: the restored card 409s again on the
      // next click, and again, forever, because there is nothing left on the
      // server for it to answer. Observed live as a user clicking a
      // never-clearing approval a dozen times, escapable only by reloading
      // the page, which refetches /state and finds no pending approval.
      // Only a 400 (validation, interrupt never spent) is genuinely
      // restorable.
      const isGone = err instanceof api.ApiError && err.status === 409;
      useChatStore.setState({
        pendingApproval: isGone ? null : (context?.previous ?? null),
        turnInProgress: false,
        approvalError: isGone ? null : message,
      });
      // A validation rejection is shown inline on the restored card, right
      // beside the textarea that needs fixing. Anything else (a 409, a
      // 500, a dropped connection) has no card-local remedy, so it still
      // goes to the global banner the rest of the chat pane uses.
      if (isGone) {
        // Not phrased as an error, because nothing the user did was wrong:
        // this approval was simply already dealt with. Saying "409 Conflict"
        // at them invites another click on a card that cannot work.
        useChatStore.getState().applyEvent({
          type: "error",
          message: "That request was already handled; the conversation has moved on since the card was shown.",
        });
      } else if (!isValidation) {
        useChatStore.getState().applyEvent({ type: "error", message });
      }
    },
  });

  const approvalError = useChatStore((s) => s.approvalError);

  const params = (pending.params as Record<string, unknown>) ?? {};
  // Which of those the app filled in because nobody said otherwise. Rendering
  // them beside the stated ones, undifferentiated, is what made a silent
  // default dangerous: the row for a value you chose and the row for a value
  // the app chose looked the same, so approving covered both without
  // distinguishing them. Marked here instead, and listed separately.
  const appliedDefaults = (pending.applied_defaults as Record<string, unknown>) ?? {};
  const defaultKeys = new Set(Object.keys(appliedDefaults));
  // The third kind of value, and the one this card could not previously show.
  // A default is the app's choice and is marked as such; a stated value is
  // yours. A value the model supplied that nothing in the conversation
  // mentions was rendering as though it were yours, which is precisely what
  // makes a guess dangerous rather than merely unhelpful -- you approve it
  // without a reason to look twice. See app/agent/grounding.py.
  const unstatedParams = (pending.unstated_params as Record<string, unknown>) ?? {};
  const unstatedKeys = new Set(Object.keys(unstatedParams));
  const kbContext = pending.kb_context as string | undefined;
  const scanNote = pending.scan_note as string | undefined;
  const paramCorrections = (pending.param_corrections as string[] | undefined) ?? [];
  // F-018: input_warnings carries {severity, message} objects now. The
  // string[] branch is a compatibility path for an approval that was
  // already pending when this shipped -- its interrupt payload was written
  // by the old code and cannot be rewritten, so an in-flight card would
  // otherwise render "- undefined" for every finding.
  const inputWarnings = (
    (pending.input_warnings as Array<string | { severity?: string; message: string }> | undefined) ?? []
  ).map((w) => (typeof w === "string" ? { severity: "warning", message: w } : w));
  const definiteProblems = inputWarnings.filter((w) => w.severity === "error");
  const advisoryWarnings = inputWarnings.filter((w) => w.severity !== "error");
  const [ackProblems, setAckProblems] = useState(false);
  const keywordOptions = pending.keyword_options as
    | { basis_options?: string[]; functional_options?: string[] }
    | undefined;

  return (
    <div className="flex justify-start">
      <div className="w-full max-w-[85%] rounded-lg border border-accent/40 bg-surface p-3.5 text-sm">
        <div className="mb-2 flex items-center justify-between">
          <div className="font-medium text-text">
            Approve {pending.task as string}
            {pending.subtype ? `/${pending.subtype as string}` : ""} job, {" "}
            {(pending.molecule_name as string) ?? "molecule"}
          </div>
          <span className="rounded bg-surface-raised px-1.5 py-0.5 font-mono text-3xs text-text-muted">
            {engine}
          </span>
        </div>

        {paramCorrections.length > 0 && (
          <div className="mb-2 rounded border border-accent/40 bg-accent-muted px-2 py-1 text-xs text-accent">
            {paramCorrections.map((note, i) => (
              <div key={i}>Auto-corrected: {note}</div>
            ))}
          </div>
        )}

        <div className="mb-2 text-xs text-text-muted" data-testid="approval-params">
          {Object.entries(params)
            .filter(([k]) => !k.startsWith("_") && !defaultKeys.has(k) && !unstatedKeys.has(k))
            .map(([k, v]) => `${k}=${JSON.stringify(v)}`)
            .join(", ")}
        </div>

        {unstatedKeys.size > 0 && (
          <div
            data-testid="approval-unstated-params"
            className="mb-2 rounded border border-status-failed/40 bg-surface-raised px-2 py-1.5 text-xs text-text-muted"
          >
            <div className="font-medium text-status-failed">
              Check these: nothing you said mentions them
            </div>
            <div className="mt-0.5">
              {Object.entries(unstatedParams)
                .map(([k, v]) => `${k}=${JSON.stringify(v)}`)
                .join(", ")}
            </div>
            <div className="mt-0.5 opacity-80">
              They may have come from earlier context, but they are not defaults and they
              are not something you stated in so many words. Correct any that are wrong
              before approving.
            </div>
          </div>
        )}

        {defaultKeys.size > 0 && (
          <div
            data-testid="approval-applied-defaults"
            className="mb-2 rounded border border-border bg-surface-raised px-2 py-1.5 text-xs text-text-muted"
          >
            <div className="font-medium text-text">
              You did not specify these, so they take their defaults
            </div>
            <div className="mt-0.5">
              {Object.entries(appliedDefaults)
                .map(([k, v]) => `${k}=${JSON.stringify(v)}`)
                .join(", ")}
            </div>
            <div className="mt-0.5 opacity-80">
              Say what you want instead if any of them matters for this job.
            </div>
          </div>
        )}

        {/* F-018: a definite defect gets its own loud, acknowledge-to-proceed
            treatment. The single yellow "possible issues (not blocking)"
            banner this replaces read as routine noise and was easy to click
            past -- which is exactly what happened on a real custom ORCA job
            whose defect the app had already diagnosed precisely, and then
            spent 33s of compute reproducing as an opaque engine error.
            Still not a hard block: `custom` exists to carry syntax this
            validator cannot model, so the human keeps the final say. They
            just have to say it deliberately. */}
        {definiteProblems.length > 0 && (
          <div
            data-testid="approval-definite-problems"
            className="mb-2 rounded border-2 border-status-failed bg-status-failed/15 px-2 py-1.5 text-xs text-status-failed"
          >
            <div className="flex items-center gap-1.5 font-semibold">
              <AlertTriangle size={13} />
              This input looks wrong and will probably fail
            </div>
            {definiteProblems.map((w, i) => (
              <div key={i} className="mt-0.5">
                - {w.message}
              </div>
            ))}
            <label className="mt-1.5 flex items-center gap-1.5 font-medium">
              <input
                type="checkbox"
                data-testid="approval-ack-problems"
                checked={ackProblems}
                onChange={(e) => setAckProblems(e.target.checked)}
              />
              Run it anyway, I know what I'm doing
            </label>
          </div>
        )}

        {advisoryWarnings.length > 0 && (
          <div
            data-testid="approval-input-warnings"
            className="mb-2 rounded border border-border bg-bg px-2 py-1 text-2xs text-text-muted"
          >
            <div className="font-medium text-text">
              Structural check didn't recognize part of this input (not blocking, often a false
              alarm on a custom job):
            </div>
            {advisoryWarnings.map((w, i) => (
              <div key={i}>- {w.message}</div>
            ))}
          </div>
        )}

        {keywordOptions && ((keywordOptions.functional_options?.length ?? 0) > 0 || (keywordOptions.basis_options?.length ?? 0) > 0) && (
          <div className="mb-2 rounded border border-border bg-bg px-2 py-1 text-2xs text-text-muted">
            <div className="mb-1 font-medium text-text">Closest-matching keyword options (informational)</div>
            {(keywordOptions.functional_options?.length ?? 0) > 0 && (
              <div>
                Functional/method:{" "}
                {keywordOptions.functional_options!.map((opt, i) => `${i + 1}) ${opt}`).join("  ")}
              </div>
            )}
            {(keywordOptions.basis_options?.length ?? 0) > 0 && (
              <div>
                Basis:{" "}
                {keywordOptions.basis_options!
                  .map((opt, i) => `${String.fromCharCode(97 + i)}) ${opt}`)
                  .join("  ")}
              </div>
            )}
          </div>
        )}

        {scanNote && <div className="mb-2 text-2xs italic text-text-muted">{scanNote}</div>}

        {editable ? (
          <textarea
            value={inputText}
            onChange={(e) => setInputText(e.target.value)}
            rows={10}
            className="mb-2 w-full resize-y rounded border border-border bg-bg p-2 font-mono text-2xs text-text outline-none focus:border-accent"
          />
        ) : (
          <pre className="mb-2 max-h-64 overflow-y-auto rounded border border-border bg-bg p-2 font-mono text-2xs text-text-muted">
            {originalInput}
          </pre>
        )}
        {!editable && (
          <div className="mb-2 text-2xs text-text-muted">
            {pending.task === "cas_reco"
              ? "This job runs multiple internal calculation stages (see above), there is no single input file to preview or edit."
              : "PySCF has no literal input file to hand-edit. This preview is a synthetic driver script."}
          </div>
        )}

        {kbContext && (
          <div className="mb-2">
            <button
              onClick={() => setKbOpen((o) => !o)}
              className="flex items-center gap-1 text-2xs text-text-muted hover:text-text"
            >
              {kbOpen ? <ChevronDown size={11} /> : <ChevronRight size={11} />}
              Manual/reference excerpts consulted
            </button>
            {kbOpen && (
              <pre className="mt-1 max-h-48 overflow-y-auto whitespace-pre-wrap rounded border border-border bg-bg p-2 text-2xs text-text-muted">
                {kbContext}
              </pre>
            )}
          </div>
        )}

        {/* F-023: a rejected hand-edit now comes back as a 400 from the
            route BEFORE the graph resumes, so the interrupt is still
            pending and this card is still live. Showing the reason here --
            next to the textarea the user has to fix -- rather than only in
            the global chat error banner is the whole point of not
            consuming the approval: fix in place, click again. */}
        {approvalError && (
          <div
            data-testid="approval-error"
            className="mb-2 rounded border border-status-failed/40 bg-status-failed/10 p-2 text-2xs text-status-failed"
          >
            {approvalError}
          </div>
        )}

        <div className="flex items-center gap-2">
          <button
            onClick={() => approveMutation.mutate(true)}
            data-testid="approval-approve"
            disabled={approveMutation.isPending || (definiteProblems.length > 0 && !ackProblems)}
            title={
              definiteProblems.length > 0 && !ackProblems
                ? "Tick the acknowledgement above to run an input the structural check flagged as malformed"
                : undefined
            }
            className="rounded bg-accent px-3 py-1.5 text-xs font-medium text-on-accent disabled:cursor-not-allowed disabled:opacity-50"
          >
            {edited ? "Run edited" : "Approve & run"}
          </button>
          <button
            onClick={() => approveMutation.mutate(false)}
            data-testid="approval-reject"
            className="rounded border border-border px-3 py-1.5 text-xs text-text-muted hover:text-text"
          >
            Reject
          </button>
          {edited && (
            <button
              onClick={() => setInputText(originalInput)}
              className="flex items-center gap-1 text-2xs text-text-muted hover:text-text"
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

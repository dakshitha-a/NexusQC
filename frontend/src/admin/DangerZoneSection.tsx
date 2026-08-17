import { AlertTriangle, Ban } from "lucide-react";
import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import * as api from "../lib/api";

/**
 * A deployment-wide purge, gated behind typing its exact phrase.
 *
 * These used to be two-click: press once to reveal a warning, press again to
 * run. That is the right weight for a per-row action, and too light for one
 * that deletes a category of data for every user at once with no undo -- two
 * clicks in the same place is a reflex, and the second one lands before the
 * warning has been read.
 *
 * Typing cannot be done by reflex. It also makes the target explicit: you type
 * PURGE ALL JOBS, so you cannot be halfway through confirming a jobs purge
 * while believing it is the chat one.
 *
 * The per-row ConfirmButton keeps its two-click behaviour; it is scoped to one
 * user or one invite, and its warning names the specific thing.
 */
function PurgeAction({
  label, description, phrase, onConfirm, pending, testId,
}: {
  label: string;
  description: string;
  phrase: string;
  onConfirm: () => void;
  pending: boolean;
  testId: string;
}) {
  const [typed, setTyped] = useState("");
  const armed = typed.trim().toUpperCase() === phrase;

  return (
    <div className="rounded border border-status-failed/30 bg-status-failed/[0.03] p-3">
      <div className="flex items-start gap-2">
        <Ban size={14} className="mt-0.5 shrink-0 text-status-failed" />
        <div className="min-w-0 flex-1">
          <div className="text-xs font-medium text-status-failed">{label}</div>
          <div className="mt-0.5 text-[11px] text-text-muted">{description}</div>
          <div className="mt-2 flex items-center gap-2">
            <label className="text-[11px] text-text-muted">
              Type <span className="font-mono font-semibold text-status-failed">{phrase}</span>
            </label>
            <input
              value={typed}
              onChange={(e) => setTyped(e.target.value)}
              placeholder={phrase}
              aria-label={`Type ${phrase} to enable`}
              data-testid={`${testId}-phrase`}
              className="min-w-0 flex-1 rounded border border-border bg-bg px-2 py-1 font-mono text-[11px] text-text placeholder:text-text-muted/40 focus:border-status-failed focus:outline-none"
            />
            <button
              onClick={() => {
                onConfirm();
                setTyped("");
              }}
              disabled={!armed || pending}
              data-testid={testId}
              className="shrink-0 rounded bg-status-failed px-3 py-1 text-[11px] font-medium text-white disabled:cursor-not-allowed disabled:opacity-25"
            >
              {pending ? "Purging..." : "Purge"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

export function DangerZoneSection({
  onMutationSuccess,
  onMutationError,
}: {
  onMutationSuccess: () => void;
  onMutationError: (error: unknown) => void;
}) {
  const purgeJobs = useMutation({ mutationFn: api.purgeAllJobs, onSuccess: onMutationSuccess, onError: onMutationError });
  const purgeKb = useMutation({ mutationFn: api.purgeAllKb, onSuccess: onMutationSuccess, onError: onMutationError });
  const purgeThreads = useMutation({ mutationFn: () => api.purgeAllThreads(false), onSuccess: onMutationSuccess, onError: onMutationError });

  return (
    <div className="space-y-3">
      <div className="flex items-start gap-2 rounded border border-status-failed/40 bg-status-failed/5 px-3 py-2.5">
        <AlertTriangle size={15} className="mt-0.5 shrink-0 text-status-failed" />
        <div className="text-xs text-status-failed">
          <div className="font-semibold">Everything here acts on every user in this deployment.</div>
          <div className="mt-0.5 text-[11px] text-status-failed/80">
            There is no undo and no confirmation step after the button. The only way back is a restore from
            backup — see scripts/restore.sh.
          </div>
        </div>
      </div>

      <PurgeAction
        label="Purge all job history"
        description="Every completed, failed and cancelled job for every user, and its artifacts on disk. Running jobs are never touched."
        phrase="PURGE ALL JOBS"
        testId="admin-purge-jobs"
        onConfirm={() => purgeJobs.mutate()}
        pending={purgeJobs.isPending}
      />
      <PurgeAction
        label="Purge all knowledge-base uploads"
        description="Every source uploaded by any user. The pre-seeded manuals are never touched."
        phrase="PURGE ALL KB"
        testId="admin-purge-kb"
        onConfirm={() => purgeKb.mutate()}
        pending={purgeKb.isPending}
      />
      <PurgeAction
        label="Purge all chat history"
        description="Every conversation and its checkpoint storage, for every user. Pinned conversations are never touched."
        phrase="PURGE ALL CHAT"
        testId="admin-purge-chat"
        onConfirm={() => purgeThreads.mutate()}
        pending={purgeThreads.isPending}
      />
    </div>
  );
}

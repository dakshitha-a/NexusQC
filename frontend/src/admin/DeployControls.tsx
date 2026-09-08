import { useEffect, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { AlertTriangle, History, PlayCircle, RotateCcw, Terminal } from "lucide-react";
import * as api from "../lib/api";
import type { AdminActivity, AdminDeployment, DestructiveFinding } from "../lib/api";
import { PurgeAction } from "./DangerZoneSection";
import { DEPLOY_ID_KEY } from "../app-shell/MaintenanceGate";

/**
 * Running an update from inside the app.
 *
 * The order the controls appear in is the order the decision is actually
 * made, and it is not the order that feels natural to build. You look at what
 * would break and who is working FIRST, and only then are you offered the
 * button -- because the whole reason this exists rather than an `Apply` that
 * just runs update.sh is that a restart kills every running calculation, and
 * on this deployment a calculation can be hours of someone's work.
 */
function Finding({ f }: { f: DestructiveFinding }) {
  const tone =
    f.severity === "destructive"
      ? "border-status-failed/40 bg-status-failed/5"
      : f.severity === "warn"
        ? "border-status-running/40 bg-status-running/5"
        : "border-border bg-surface";
  return (
    <div className={`rounded border px-2.5 py-1.5 ${tone}`}>
      <div className="text-[11px] font-medium text-text">{f.title}</div>
      {f.detail.trim() && (
        <pre className="mt-1 whitespace-pre-wrap font-mono text-[10px] leading-snug text-text-muted">
          {f.detail.trim()}
        </pre>
      )}
    </div>
  );
}

export function DeployControls({
  deployment,
  activity,
  onMutationError,
  onMutationSuccess,
}: {
  deployment: AdminDeployment | undefined;
  activity: AdminActivity | undefined;
  onMutationError: (e: unknown) => void;
  onMutationSuccess: () => void;
}) {
  const [runId, setRunId] = useState<string | null>(null);
  const runner = deployment?.runner;

  // Polled only while a run is in flight. `refetchInterval` returning false
  // stops it, so a finished run costs nothing.
  const run = useQuery({
    queryKey: ["admin", "deploy", runId],
    queryFn: () => api.getAdminDeploy(runId as string),
    enabled: Boolean(runId),
    refetchInterval: (q) => {
      const st = q.state.data?.status?.state;
      return st === "done" || st === "failed" ? false : 2000;
    },
  });

  const submit = useMutation({
    mutationFn: api.postAdminDeploy,
    onSuccess: (r) => {
      setRunId(r.id);
      // The overlay in MaintenanceGate reads this to know which run to watch
      // through nginx once the api goes away mid-restart. sessionStorage
      // rather than state, because the point is that it survives the reload.
      try {
        if (r.action === "update" || r.action === "rollback") {
          window.sessionStorage.setItem(DEPLOY_ID_KEY, r.id);
        }
      } catch {
        /* storage blocked; the overlay falls back to polling /api/health */
      }
      onMutationSuccess();
    },
    onError: onMutationError,
  });

  // Re-attach to a run this tab started but has since reloaded past.
  useEffect(() => {
    try {
      const saved = window.sessionStorage.getItem(DEPLOY_ID_KEY);
      if (saved && !runId) setRunId(saved);
    } catch {
      /* nothing to re-attach to */
    }
  }, [runId]);

  const report = run.data?.report;
  const state = run.data?.status?.state;
  const busy = state === "queued" || state === "running";
  const action = run.data?.request?.action;

  const othersInterrupted = activity?.totals.others_interrupted ?? 0;
  const runningJobs = activity?.totals.running_jobs ?? 0;
  const destructive = report?.destructive ?? 0;

  if (!runner?.installed || !runner.alive) {
    return (
      <section>
        <h3 className="mb-1 flex items-center gap-1.5 text-xs font-semibold text-text">
          <Terminal size={13} /> Updating
        </h3>
        <div className="rounded border border-border bg-surface px-3 py-3 text-[11px] leading-relaxed text-text-muted">
          {runner?.installed
            ? "The update service is installed on the host but is not responding, so nothing would pick up a request from here."
            : "Updates run on the host. Nothing is installed here to accept a request from the app, which is the default."}
          <div className="mt-2 font-mono text-[10px] text-text">
            scripts/update.sh
          </div>
          <div className="mt-2">
            To update from this panel instead, run{" "}
            <code className="font-mono text-[10px] text-text">scripts/install_updater.sh</code>{" "}
            on the host once. Everything above this section works either way.
          </div>
        </div>
      </section>
    );
  }

  return (
    <section>
      <h3 className="mb-1 flex items-center gap-1.5 text-xs font-semibold text-text">
        <PlayCircle size={13} /> Updating
      </h3>

      {/* Step one: find out what it would do. Read-only, changes nothing. */}
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <button
          onClick={() => submit.mutate({ action: "report" })}
          disabled={submit.isPending || busy}
          data-testid="deploy-preview"
          className="rounded bg-accent px-2.5 py-1 text-[11px] font-medium text-white disabled:opacity-30"
        >
          Check what an update would do
        </button>
        {busy && action === "report" && (
          <span className="text-[11px] text-text-muted">checking…</span>
        )}
      </div>

      {report && (
        <div className="mb-3 space-y-1.5">
          <div className="text-[11px] text-text-muted">
            {report.from.slice(0, 12)} → {report.to.slice(0, 12)}
            {report.from === report.to && " (already up to date)"}
          </div>
          {report.findings
            .filter((f) => f.severity === "destructive" || f.severity === "warn")
            .map((f, i) => (
              <Finding key={i} f={f} />
            ))}
          {report.findings.every((f) => f.severity === "ok" || f.severity === "skipped") && (
            <div className="rounded border border-border bg-surface px-2.5 py-1.5 text-[11px] text-text-muted">
              Nothing destructive and nothing to warn about.
            </div>
          )}
        </div>
      )}

      {/* Step two: who this costs. Restated here rather than left to the
          table above, because this is the moment the decision is made and
          scrolling back up to check is exactly what nobody does. */}
      {(othersInterrupted > 0 || runningJobs > 0) && (
        <div className="mb-2 flex items-start gap-2 rounded border border-status-running/40 bg-status-running/5 px-3 py-2 text-[11px] text-text">
          <AlertTriangle size={13} className="mt-px shrink-0 text-status-running" />
          <div>
            {runningJobs > 0 && (
              <>
                <strong>{runningJobs}</strong> calculation{runningJobs === 1 ? "" : "s"} running.
                Restarting kills {runningJobs === 1 ? "it" : "them"}; there is no resume.{" "}
              </>
            )}
            {othersInterrupted > 0 && (
              <>
                <strong>{othersInterrupted}</strong> other user
                {othersInterrupted === 1 ? "" : "s"} would be logged out.
              </>
            )}
            <div className="mt-1 text-text-muted">
              Draining waits for running jobs to finish before anyone is logged out, however
              long that takes. Everyone stays logged in and working while it waits.
            </div>
          </div>
        </div>
      )}

      {/* Step three, and only now. A typed phrase, the same shape every other
          irreversible action in this panel uses. */}
      <div className="space-y-2">
        <PurgeAction
          label="Update this deployment"
          description={
            "Waits for running calculations to finish, then logs everyone out, rebuilds and " +
            "restarts. Takes a full backup first. Browsers reload themselves when it is done."
          }
          phrase="UPDATE"
          pending={submit.isPending || (busy && action === "update")}
          testId="deploy-update"
          onConfirm={() => submit.mutate({ action: "update", drain: true })}
        />
        {destructive > 0 && (
          <div className="text-[11px] text-status-failed">
            The report above found {destructive} destructive change
            {destructive === 1 ? "" : "s"}. Read {destructive === 1 ? "it" : "them"} before typing
            UPDATE.
          </div>
        )}
        <PurgeAction
          label="Roll back to the previous deployment"
          description={
            "Returns to the commit that was running before the last successful update, and " +
            "restarts. Data written since then is not rolled back."
          }
          phrase="ROLLBACK"
          pending={submit.isPending || (busy && action === "rollback")}
          testId="deploy-rollback"
          onConfirm={() => submit.mutate({ action: "rollback" })}
        />
      </div>

      {/* Progress. The overlay covers this once the api goes away; this is
          what an admin watches for a report or the early part of an update. */}
      {run.data && (
        <div className="mt-3 rounded border border-border bg-surface px-3 py-2">
          <div className="flex items-center justify-between text-[11px]">
            <span className="text-text">{run.data.status.step ?? state ?? "…"}</span>
            <span
              className={
                state === "failed"
                  ? "text-status-failed"
                  : state === "done"
                    ? "text-status-running"
                    : "text-text-muted"
              }
            >
              {state}
            </span>
          </div>
          {run.data.status.error && (
            <div className="mt-1 font-mono text-[10px] text-status-failed">
              {run.data.status.error}
            </div>
          )}
          {run.data.log.trim() && (
            <pre className="mt-2 max-h-40 overflow-auto whitespace-pre-wrap font-mono text-[10px] leading-snug text-text-muted">
              {run.data.log.slice(-4000)}
            </pre>
          )}
        </div>
      )}

      {deployment && deployment.history.length > 0 && (
        <div className="mt-4">
          <h4 className="mb-1 flex items-center gap-1.5 text-[11px] font-semibold text-text">
            <History size={12} /> Past updates
          </h4>
          <div className="rounded border border-border bg-surface px-3">
            {deployment.history.map((h, i) => (
              <div
                key={i}
                className="flex items-center justify-between gap-3 border-b border-border py-1.5 text-[11px] last:border-b-0"
              >
                <span className="font-mono text-text-muted">{h.at}</span>
                <span className="font-mono text-text-muted">
                  {h.from.slice(0, 8)} → {h.to.slice(0, 8)}
                </span>
                <span className={h.verb === "updated" ? "text-status-running" : "text-status-failed"}>
                  {h.verb === "updated" ? "ok" : h.verb}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="mt-3 flex items-center gap-1.5 text-[10px] text-text-muted">
        <RotateCcw size={10} />
        Every update takes a full backup before it touches anything.
      </div>
    </section>
  );
}

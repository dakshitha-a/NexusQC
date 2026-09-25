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
      <div className="text-2xs font-medium text-text">{f.title}</div>
      {f.detail.trim() && (
        <pre className="mt-1 whitespace-pre-wrap font-mono text-3xs leading-snug text-text-muted">
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
  // How long users are warned, and an optional note to them. The default
  // matches update.sh's QC_AGENT_UPDATE_NOTICE_MINUTES default.
  const [noticeMinutes, setNoticeMinutes] = useState(10);
  const [noticeMessage, setNoticeMessage] = useState("");
  const runner = deployment?.runner;
  // Shares the banner's cache key, so this costs no extra request.
  const notice = useQuery({ queryKey: ["notice"], queryFn: api.getNotice, refetchInterval: 15_000 });
  // While an update is announced, the update and rollback buttons show as
  // busy: a second request would queue a second update behind the first.
  const cancellable = ["scheduled", "waiting_for_jobs", "imminent"].includes(notice.data?.notice?.phase ?? "");

  // Polled only while a run is in flight. `refetchInterval` returning false
  // stops it, so a finished run costs nothing.
  const run = useQuery({
    queryKey: ["admin", "deploy", runId],
    queryFn: () => api.getAdminDeploy(runId as string),
    enabled: Boolean(runId),
    refetchInterval: (q) => {
      const st = q.state.data?.status?.state;
      return st === "done" || st === "failed" || st === "cancelled" ? false : 2000;
    },
  });

  const submit = useMutation({
    mutationFn: api.postAdminDeploy,
    onSuccess: (r) => {
      // A cancel is not a run: the update being cancelled is the one already
      // on screen, and the id that comes back is the notice's, not a run's.
      if (r.action !== "cancel") setRunId(r.id);
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
  // Whose calculations the override would stop, named rather than counted:
  // this is the moment somebody decides to throw away hours of someone's work.
  const running = (activity?.users ?? []).filter((u) => u.running_jobs > 0);
  const unownedRunning = activity?.unowned.running_jobs ?? 0;
  const noticeOk = Number.isInteger(noticeMinutes) && noticeMinutes >= 0 && noticeMinutes <= 120;
  const noticeFields = {
    notice_minutes: noticeOk ? noticeMinutes : 10,
    message: noticeMessage.trim() || undefined,
  };

  if (!runner?.installed || !runner.alive) {
    return (
      <section>
        <h3 className="mb-1 flex items-center gap-1.5 text-xs font-semibold text-text">
          <Terminal size={13} /> Updating
        </h3>
        <div className="rounded border border-border bg-surface px-3 py-3 text-2xs leading-relaxed text-text-muted">
          {runner?.installed
            ? "The update service is installed on the host but is not responding, so nothing would pick up a request from here."
            : "Updates run on the host. Nothing is installed here to accept a request from the app, which is the default."}
          <div className="mt-2 font-mono text-3xs text-text">
            scripts/update.sh
          </div>
          <div className="mt-2">
            To update from this panel instead, run{" "}
            <code className="font-mono text-3xs text-text">scripts/install_updater.sh</code>{" "}
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
          className="rounded bg-accent px-2.5 py-1 text-2xs font-medium text-on-accent disabled:opacity-30"
        >
          Check what an update would do
        </button>
        {busy && action === "report" && (
          <span className="text-2xs text-text-muted">checking…</span>
        )}
      </div>

      {report && (
        <div className="mb-3 space-y-1.5">
          <div className="text-2xs text-text-muted">
            {report.from.slice(0, 12)} → {report.to.slice(0, 12)}
            {report.from === report.to && " (already up to date)"}
          </div>
          {report.findings
            .filter((f) => f.severity === "destructive" || f.severity === "warn")
            .map((f, i) => (
              <Finding key={i} f={f} />
            ))}
          {(run.data?.changes?.length ?? 0) > 0 && (
            <details className="rounded border border-border bg-surface px-2.5 py-1.5">
              <summary className="cursor-pointer text-2xs text-text">
                {run.data!.changes.length} change
                {run.data!.changes.length === 1 ? "" : "s"} this would bring in
              </summary>
              <pre className="mt-1 max-h-40 overflow-auto whitespace-pre-wrap font-mono text-3xs leading-snug text-text-muted">
                {run.data!.changes.join("\n")}
              </pre>
            </details>
          )}
          {report.findings.every((f) => f.severity === "ok" || f.severity === "skipped") && (
            <div className="rounded border border-border bg-surface px-2.5 py-1.5 text-2xs text-text-muted">
              Nothing destructive and nothing to warn about.
            </div>
          )}
        </div>
      )}

      {/* Step two: who this costs. Restated here rather than left to the
          table above, because this is the moment the decision is made and
          scrolling back up to check is exactly what nobody does. */}
      {(othersInterrupted > 0 || runningJobs > 0) && (
        <div className="mb-2 flex items-start gap-2 rounded border border-status-running/40 bg-status-running/5 px-3 py-2 text-2xs text-text">
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
                {othersInterrupted === 1 ? " has" : "s have"} the app open. They are warned in
                advance, locked out for the restart, and stay signed in.
              </>
            )}
            <div className="mt-1 text-text-muted">
              An update waits for running calculations to finish before the restart, however
              long that takes. Everyone keeps working while it waits; new calculations queue.
            </div>
          </div>
        </div>
      )}

      {/* Step three, and only now. A typed phrase, the same shape every other
          irreversible action in this panel uses. */}
      <div className="space-y-2">
        {/* What users are told. Everyone with the app open sees a banner with
            a countdown to the restart, and the note below it if there is one. */}
        <div className="rounded border border-border bg-surface px-3 py-2" data-testid="deploy-notice-settings">
          <div className="text-2xs font-medium text-text">Warning to users</div>
          <label className="mt-1.5 flex items-center gap-2 text-2xs text-text-muted">
            Restart
            <input
              type="number"
              min={0}
              max={120}
              step={1}
              value={Number.isNaN(noticeMinutes) ? "" : noticeMinutes}
              onChange={(e) => setNoticeMinutes(e.target.value === "" ? NaN : Number(e.target.value))}
              data-testid="deploy-notice-minutes"
              className="w-14 rounded border border-border bg-bg px-1.5 py-0.5 text-2xs text-text"
            />
            minutes after the update is started. The image is built during this time.
          </label>
          {!noticeOk && (
            <div className="mt-1 text-2xs text-status-failed">Choose a whole number of minutes from 0 to 120.</div>
          )}
          <textarea
            value={noticeMessage}
            onChange={(e) => setNoticeMessage(e.target.value.slice(0, 500))}
            placeholder="Optional note to users, for example what the update brings"
            rows={2}
            data-testid="deploy-notice-message"
            className="mt-1.5 w-full resize-y rounded border border-border bg-bg px-2 py-1 text-2xs text-text placeholder:text-text-muted"
          />
        </div>

        {cancellable && (
          <div className="flex items-center gap-2 rounded border border-status-running/40 bg-status-running/5 px-3 py-2 text-2xs text-text">
            <span className="flex-1">
              An update is announced and has not locked anyone out yet. You can still call it off.
            </span>
            <button
              onClick={() => submit.mutate({ action: "cancel" })}
              disabled={submit.isPending}
              data-testid="deploy-cancel"
              className="rounded border border-border px-2.5 py-1 text-2xs text-text hover:bg-surface-raised disabled:opacity-30"
            >
              Cancel the update
            </button>
          </div>
        )}

        <PurgeAction
          label="Update this deployment"
          description={
            `Warns everyone in the app, restarts ${noticeOk ? noticeMinutes : 10} minutes from now, and ` +
            "waits longer if calculations are still running. Non-admins are locked out for the restart, " +
            "a minute or two, and stay signed in. Takes a full backup first. Browsers reload themselves " +
            "when it is done."
          }
          phrase="UPDATE"
          pending={submit.isPending || (busy && action === "update") || cancellable}
          testId="deploy-update"
          actionLabel="Update"
          pendingLabel="Updating..."
          onConfirm={() => submit.mutate({ action: "update", drain: true, ...noticeFields })}
        />
        {(running.length > 0 || unownedRunning > 0) && (
          <PurgeAction
            label="Stop running calculations and update"
            description={
              "Does not wait. Calculations still running at the restart are killed and cannot be " +
              "resumed: " +
              [
                ...running.map((u) => `${u.username} (${u.running_jobs})`),
                ...(unownedRunning > 0 ? [`${unownedRunning} with no owner`] : []),
              ].join(", ") +
              ". Users are warned in advance that their calculations will be stopped."
            }
            phrase="STOP AND UPDATE"
            pending={submit.isPending || (busy && action === "update") || cancellable}
            testId="deploy-update-force"
            actionLabel="Stop and update"
            pendingLabel="Updating..."
            onConfirm={() => submit.mutate({ action: "update", drain: false, force: true, ...noticeFields })}
          />
        )}
        {destructive > 0 && (
          <div className="text-2xs text-status-failed">
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
          pending={submit.isPending || (busy && action === "rollback") || cancellable}
          testId="deploy-rollback"
          actionLabel="Roll back"
          pendingLabel="Rolling back..."
          onConfirm={() => submit.mutate({ action: "rollback", ...noticeFields })}
        />
      </div>

      {/* Progress. The overlay covers this once the api goes away; this is
          what an admin watches for a report or the early part of an update. */}
      {run.data && (
        <div className="mt-3 rounded border border-border bg-surface px-3 py-2">
          <div className="flex items-center justify-between text-2xs">
            <span className="text-text">{run.data.status.step ?? state ?? "…"}</span>
            <span
              className={
                state === "failed"
                  ? "text-status-failed"
                  : state === "cancelled"
                    ? "text-text-muted"
                  : state === "done"
                    ? "text-status-running"
                    : "text-text-muted"
              }
            >
              {state}
            </span>
          </div>
          {run.data.status.error && (
            <div className="mt-1 font-mono text-3xs text-status-failed">
              {run.data.status.error}
            </div>
          )}
          {run.data.log.trim() && (
            <pre className="mt-2 max-h-40 overflow-auto whitespace-pre-wrap font-mono text-3xs leading-snug text-text-muted">
              {run.data.log.slice(-4000)}
            </pre>
          )}
        </div>
      )}

      {deployment && deployment.history.length > 0 && (
        <div className="mt-4">
          <h4 className="mb-1 flex items-center gap-1.5 text-2xs font-semibold text-text">
            <History size={12} /> Past updates
          </h4>
          <div className="rounded border border-border bg-surface px-3">
            {deployment.history.map((h, i) => (
              <div
                key={i}
                className="flex items-center justify-between gap-3 border-b border-border py-1.5 text-2xs last:border-b-0"
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

      <div className="mt-3 flex items-center gap-1.5 text-3xs text-text-muted">
        <RotateCcw size={10} />
        Every update takes a full backup before it touches anything.
      </div>
    </section>
  );
}

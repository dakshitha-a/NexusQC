import { useEffect, useState } from "react";

/**
 * What everyone sees while the deployment is being updated.
 *
 * The hard part is not the overlay, it is staying informative while the api is
 * gone. `docker compose up -d` recreates the api container, and its health
 * check has a ninety-second start period -- so for a minute and a half there
 * is nothing to ask. A progress view that stops moving for that long is
 * indistinguishable from one that has crashed, which is what makes people
 * reload into a broken state or give up on an update that was fine.
 *
 * So this polls nginx, not the api. nginx serves data/deploy read-only at
 * /deploy-status/, it is not recreated by an api-only rebuild, and it keeps
 * answering the whole way through. A failed fetch is treated as "still
 * updating" rather than as an error, so the overlay also survives nginx itself
 * bouncing -- it just goes quiet for a moment and picks the story back up.
 *
 * When the run reports done, the page hard-reloads. index.html is served
 * no-store and /assets/ is immutable-and-content-hashed (nginx/nginx.conf), so
 * a reload genuinely lands on the new bundle rather than a cached old one.
 */
type Status = {
  state?: "queued" | "running" | "done" | "failed";
  step?: string;
  error?: string;
  exit_code?: number;
};

const POLL_MIN_MS = 2000;
const POLL_MAX_MS = 10000;
// Long enough to cover a slow image build plus the api's 90s start period,
// short enough that a genuinely dead update eventually says so instead of
// spinning forever.
const GIVE_UP_MS = 30 * 60 * 1000;

export function MaintenanceOverlay({
  message,
  deployId,
  isAdmin,
  onDismiss,
}: {
  message: string;
  deployId: string | null;
  isAdmin: boolean;
  onDismiss: () => void;
}) {
  const [status, setStatus] = useState<Status | null>(null);
  const [elapsed, setElapsed] = useState(0);
  const [gaveUp, setGaveUp] = useState(false);

  useEffect(() => {
    let stop = false;
    let delay = POLL_MIN_MS;
    const started = Date.now();

    async function tick() {
      if (stop) return;
      setElapsed(Date.now() - started);

      // Two independent signals. The status file says what the runner is
      // doing; /api/health answers again the moment the new api is up, which
      // is the one that matters when there is no runner (someone updated from
      // a shell) and there is no status file to read at all.
      let done = false;
      if (deployId) {
        try {
          const r = await fetch(`/deploy-status/${deployId}/status.json`, { cache: "no-store" });
          if (r.ok) {
            const s: Status = await r.json();
            setStatus(s);
            if (s.state === "done") done = true;
            if (s.state === "failed") { setGaveUp(true); stop = true; return; }
          }
        } catch {
          /* the api is mid-restart, or nginx blinked. Neither is an error. */
        }
      }
      if (!done) {
        try {
          const h = await fetch("/api/health", { cache: "no-store" });
          if (h.ok && !deployId) done = true;
        } catch {
          /* still down */
        }
      }

      if (done) {
        window.location.reload();
        return;
      }
      if (Date.now() - started > GIVE_UP_MS) { setGaveUp(true); stop = true; return; }

      delay = Math.min(Math.round(delay * 1.25), POLL_MAX_MS);
      window.setTimeout(tick, delay);
    }

    const id = window.setTimeout(tick, POLL_MIN_MS);
    return () => { stop = true; window.clearTimeout(id); };
  }, [deployId]);

  const failed = status?.state === "failed" || gaveUp;
  const mins = Math.floor(elapsed / 60000);
  const secs = Math.floor((elapsed % 60000) / 1000);

  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center bg-bg/95 backdrop-blur-sm">
      <div className="mx-4 w-full max-w-md rounded-lg border border-border bg-surface p-6 shadow-lg">
        <div className="mb-3 flex items-center gap-2.5">
          {!failed && (
            <span className="inline-block h-3.5 w-3.5 animate-spin rounded-full border-2 border-accent border-t-transparent" />
          )}
          <h2 className="text-sm font-semibold text-text">
            {failed ? "The update did not finish" : "NexusQC is being updated"}
          </h2>
        </div>

        <p className="text-xs leading-relaxed text-text-muted">
          {failed
            ? "The deployment was left as it was and your work is intact. An administrator needs to look at the update log on the host."
            : message}
        </p>

        {status?.step && !failed && (
          <div className="mt-3 rounded border border-border bg-bg px-3 py-2 font-mono text-2xs text-text-muted">
            {status.step}
          </div>
        )}
        {failed && status?.error && (
          <div className="mt-3 rounded border border-status-failed/40 bg-status-failed/5 px-3 py-2 font-mono text-2xs text-text">
            {status.error}
          </div>
        )}

        <p className="mt-3 text-2xs text-text-muted">
          {failed
            ? "You can keep this page open; reloading is safe."
            : `This page will reload itself when the update is done. Elapsed ${mins}m ${String(secs).padStart(2, "0")}s.`}
        </p>

        {/* An admin driving the update needs the panel underneath this, and
            the routes it uses are exempt from maintenance mode for exactly
            that reason. Everyone else has nothing useful to do here, so they
            get no way to click past it into an app that will 503 anyway. */}
        {isAdmin && (
          <button
            onClick={onDismiss}
            className="mt-4 rounded border border-border px-3 py-1.5 text-2xs text-text hover:bg-surface-raised"
          >
            Hide this and keep using the admin panel
          </button>
        )}
      </div>
    </div>
  );
}

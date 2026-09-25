import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, CheckCircle2, Clock, RefreshCw, X } from "lucide-react";
import * as api from "../lib/api";
import type { UpdateNotice } from "../lib/api";

/**
 * The strip across the top of the app that tells everyone an update is coming,
 * is under way, or has finished.
 *
 * scripts/update.sh writes the notice as the update moves along, and every tab
 * reads it from GET /api/notice every 15 seconds and whenever the tab regains
 * focus. That route is public and exempt from maintenance mode, so this shows
 * on the sign-in screen too, and keeps answering through the lockout.
 *
 * The countdown runs on the server's clock. The response carries the server's
 * `now`, and the difference from this machine's clock is applied to every
 * tick, because a laptop a few minutes out would otherwise tell someone they
 * had time they did not.
 *
 * The lockout itself is MaintenanceOverlay's job. This banner is what people
 * see before it and after it.
 */
const POLL_MS = 15_000;
const DISMISSED_KEY = "nexusqc.notice.dismissed";

function readDismissed(): string | null {
  try {
    return window.localStorage.getItem(DISMISSED_KEY);
  } catch {
    return null;
  }
}

function writeDismissed(id: string) {
  try {
    window.localStorage.setItem(DISMISSED_KEY, id);
  } catch {
    /* storage blocked: it just comes back on the next load */
  }
}

function clock(epochSeconds: number): string {
  return new Date(epochSeconds * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function countdown(seconds: number): string {
  const s = Math.max(0, Math.round(seconds));
  const m = Math.floor(s / 60);
  const r = s % 60;
  return m > 0 ? `${m}m ${String(r).padStart(2, "0")}s` : `${r}s`;
}

type Tone = "warn" | "urgent" | "ok" | "neutral";

function describe(n: UpdateNotice, secondsLeft: number | null): { tone: Tone; text: string; dismissible: boolean } {
  const when = n.restart_at ? clock(n.restart_at) : "";
  // Past the announced time but not yet restarted: the image build ran long.
  // update.sh cannot repost while the build is blocking it, and it always
  // gives a fresh minute's warning afterwards, so say that rather than
  // counting "in 0s" for several minutes.
  const overdue = secondsLeft !== null && secondsLeft < 0;
  const left = secondsLeft !== null && !overdue ? ` (in ${countdown(secondsLeft)})` : "";
  const jobs = n.stops_running_jobs
    ? " Calculations still running then will be stopped."
    : " You stay signed in, and running calculations are not interrupted: the update waits for them.";
  switch (n.phase) {
    case "scheduled":
      return {
        tone: "warn",
        text:
          (overdue
            ? "NexusQC will restart for an update shortly, once the update is ready, with a minute's warning."
            : `NexusQC will restart for an update at ${when}${left}.`) +
          " It will be unavailable for a minute or two." +
          jobs + " New calculations you submit now will queue and start after the update.",
        dismissible: false,
      };
    case "waiting_for_jobs":
      return {
        tone: "warn",
        text:
          `An update is waiting for ${n.waiting_jobs} running calculation${n.waiting_jobs === 1 ? "" : "s"} to finish. ` +
          "New calculations you submit now will queue and start after the update.",
        dismissible: false,
      };
    case "imminent":
      return {
        tone: "urgent",
        text: `NexusQC is about to restart for an update${left}. Finish what you are typing; you will stay signed in.`,
        dismissible: false,
      };
    case "in_progress":
      return { tone: "urgent", text: "NexusQC is restarting for an update.", dismissible: false };
    case "done":
      return {
        tone: "ok",
        text: `NexusQC was updated at ${clock(n.updated_at)}. Queued calculations are starting again.`,
        dismissible: true,
      };
    case "failed":
      return {
        tone: "neutral",
        text: "An update did not finish. Nothing changed for you, and your work is intact.",
        dismissible: true,
      };
    case "cancelled":
      return {
        tone: "neutral",
        text: `The update planned${when ? ` for ${when}` : ""} was cancelled. Queued calculations are starting again.`,
        dismissible: true,
      };
  }
}

const TONE_CLASS: Record<Tone, string> = {
  warn: "border-status-running/40 bg-status-running/10 text-text",
  urgent: "border-status-failed/50 bg-status-failed/10 text-text",
  ok: "border-accent/40 bg-accent/10 text-text",
  neutral: "border-border bg-surface text-text",
};

export function UpdateNoticeBanner() {
  const q = useQuery({
    queryKey: ["notice"],
    queryFn: api.getNotice,
    // Every 3 s around the restart, so the overlay goes up within seconds
    // of the lockout; every 15 s otherwise.
    refetchInterval: (query) =>
      ["imminent", "in_progress"].includes(query.state.data?.notice?.phase ?? "") ? 3000 : POLL_MS,
    refetchOnWindowFocus: true,
    retry: false,
  });
  const [dismissed, setDismissed] = useState<string | null>(readDismissed);
  const [, setTick] = useState(0);

  const notice = q.data?.notice ?? null;
  const lockedOut = Boolean(q.data?.maintenance) || notice?.phase === "in_progress";

  // Raise the lockout overlay as soon as the notice says the restart has
  // begun, rather than waiting for a request to come back 503: between the
  // lockout starting and the new api answering, nginx returns gateway errors,
  // and a tab that only listened for 503s showed broken panels meanwhile.
  useEffect(() => {
    if (lockedOut) api.announceMaintenance();
  }, [lockedOut]);
  const counting =
    notice && notice.restart_at && (notice.phase === "scheduled" || notice.phase === "imminent");

  // A one-second tick only while there is a countdown on screen.
  useEffect(() => {
    if (!counting) return;
    const id = window.setInterval(() => setTick((t) => t + 1), 1000);
    return () => window.clearInterval(id);
  }, [counting]);

  if (!notice) return null;
  if (dismissed === notice.id + ":" + notice.phase) return null;

  // Server clock minus this machine's, fixed at the moment the answer arrived.
  const skew = q.data ? q.data.now - q.dataUpdatedAt / 1000 : 0;
  const secondsLeft = counting ? (notice.restart_at as number) - (Date.now() / 1000 + skew) : null;
  const { tone, text, dismissible } = describe(notice, secondsLeft);
  const Icon =
    notice.phase === "done" ? CheckCircle2 : tone === "urgent" ? RefreshCw : tone === "warn" ? Clock : AlertTriangle;

  return (
    <div
      role="status"
      aria-live="polite"
      data-testid="update-notice"
      data-phase={notice.phase}
      className={`flex shrink-0 items-start gap-2 border-b px-4 py-2 text-xs leading-snug ${TONE_CLASS[tone]}`}
    >
      <Icon size={14} className={`mt-px shrink-0 ${notice.phase === "in_progress" ? "animate-spin" : ""}`} />
      <div className="min-w-0 flex-1">
        <span>{text}</span>
        {notice.message && (
          <span className="mt-0.5 block text-text-muted" data-testid="update-notice-message">
            From the administrator: {notice.message}
          </span>
        )}
      </div>
      {dismissible && (
        <button
          onClick={() => {
            const key = notice.id + ":" + notice.phase;
            writeDismissed(key);
            setDismissed(key);
          }}
          aria-label="Dismiss"
          data-testid="update-notice-dismiss"
          className="shrink-0 rounded p-0.5 text-text-muted hover:bg-surface-raised hover:text-text"
        >
          <X size={13} />
        </button>
      )}
    </div>
  );
}

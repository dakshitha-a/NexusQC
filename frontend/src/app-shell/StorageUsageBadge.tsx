import type { StorageQuota } from "../lib/api";

// GB here means the same decimal gigabyte (1000^3) the two quota.py
// modules' own docstrings ("100GB", "10GB") mean -- matches how disk usage
// is normally advertised, rather than a binary GiB reading that would make
// "100GB" as displayed here not quite match "100GB" as configured.
function formatGB(bytes: number): string {
  const gb = bytes / 1_000_000_000;
  return `${gb < 10 ? gb.toFixed(2) : gb.toFixed(1)} GB`;
}

/** Above this, the number is worth showing as text. Below it the ring is
 *  enough: "0.00 GB / 2.00 GB" is not news. */
const LOUD_AT_PCT = 80;

const SIZE = 14;
const R = 5.5;
const CIRCUMFERENCE = 2 * Math.PI * R;

/**
 * How full a disk-usage cap is, drawn as a ring.
 *
 * ## What this replaced, and why
 *
 * A line reading "0.00 GB / 2.00 GB" with a fill bar, rendered in the
 * `subHeader` slot of the Knowledge base and Files sections, which meant it
 * held a whole row of the sidebar open at all times, in both sections, whether
 * or not it had anything to say. The sidebar is where the conversation list
 * lives, and vertical space there is the scarcest in the app.
 *
 * The ring keeps the at-a-glance signal the readout existed for. These caps
 * evict oldest-first once reached (app/rag/quota.py, app/chemistry/jobs/
 * quota.py), so "how close am I to losing things" is worth seeing without
 * asking for it. The exact numbers are on hover, and they come back as text on
 * their own at {@link LOUD_AT_PCT} per cent, which is where they stop being
 * trivia.
 *
 * Hover text is a plain `title` rather than a Radix tooltip. The dependency is
 * installed but unused, and every other hint in this app is a `title`; adding
 * a second idiom for one badge would be the odd one out.
 */
export function StorageUsageBadge({ quota, label }: { quota: StorageQuota | undefined; label: string }) {
  if (!quota) return null;
  const pct = quota.quota_bytes > 0 ? Math.min(100, (quota.used_bytes / quota.quota_bytes) * 100) : 0;
  const tone = pct >= 95 ? "text-status-failed" : pct >= LOUD_AT_PCT ? "text-status-running" : "text-accent";
  const loud = pct >= LOUD_AT_PCT;

  return (
    <div
      className="flex shrink-0 items-center gap-1.5"
      data-testid="storage-gauge"
      title={`${label}: ${formatGB(quota.used_bytes)} of ${formatGB(quota.quota_bytes)} used (${pct.toFixed(1)}%). Oldest entries are evicted automatically once this cap is reached`}
    >
      {loud && (
        <span className={`text-3xs tabular-nums ${tone}`}>
          {formatGB(quota.used_bytes)} / {formatGB(quota.quota_bytes)}
        </span>
      )}
      {/* Rotated so the arc starts at twelve o'clock, which is where a gauge
          is read from, rather than at three. */}
      <svg width={SIZE} height={SIZE} viewBox={`0 0 ${SIZE} ${SIZE}`} aria-hidden="true" className={`-rotate-90 ${tone}`}>
        <circle cx={SIZE / 2} cy={SIZE / 2} r={R} fill="none" strokeWidth={2} className="stroke-border" />
        <circle
          cx={SIZE / 2}
          cy={SIZE / 2}
          r={R}
          fill="none"
          strokeWidth={2}
          strokeLinecap="round"
          stroke="currentColor"
          strokeDasharray={CIRCUMFERENCE}
          strokeDashoffset={CIRCUMFERENCE * (1 - pct / 100)}
          className="transition-[stroke-dashoffset] duration-base ease-standard"
        />
      </svg>
    </div>
  );
}

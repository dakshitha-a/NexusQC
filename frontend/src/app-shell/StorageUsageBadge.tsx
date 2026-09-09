import type { StorageQuota } from "../lib/api";

// GB here means the same decimal gigabyte (1000^3) the two quota.py
// modules' own docstrings ("100GB", "10GB") mean -- matches how disk usage
// is normally advertised, rather than a binary GiB reading that would make
// "100GB" as displayed here not quite match "100GB" as configured.
function formatGB(bytes: number): string {
  const gb = bytes / 1_000_000_000;
  return `${gb < 10 ? gb.toFixed(2) : gb.toFixed(1)} GB`;
}

/** Small "used / cap" readout with a thin fill bar, shared by the
 * Knowledge base and Job Manager panel headers -- both are backed by a
 * disk-usage cap (app/rag/quota.py, app/chemistry/jobs/quota.py) that
 * evicts oldest-first once exceeded, so this is meant as an at-a-glance
 * "how close is this to self-evicting" signal, not just a raw byte count. */
export function StorageUsageBadge({ quota, label }: { quota: StorageQuota | undefined; label: string }) {
  if (!quota) return null;
  const pct = quota.quota_bytes > 0 ? Math.min(100, (quota.used_bytes / quota.quota_bytes) * 100) : 0;
  const barColor = pct >= 95 ? "bg-status-failed" : pct >= 80 ? "bg-status-running" : "bg-accent";

  return (
    <div
      className="flex shrink-0 items-center gap-1.5"
      title={`${label}: ${formatGB(quota.used_bytes)} of ${formatGB(quota.quota_bytes)} used (${pct.toFixed(1)}%) -- oldest entries are auto-evicted once this cap is reached`}
    >
      <span className="text-3xs tabular-nums text-text-muted">
        {formatGB(quota.used_bytes)} / {formatGB(quota.quota_bytes)}
      </span>
      <div className="h-1.5 w-10 overflow-hidden rounded-full bg-surface-raised">
        <div
          className={`h-full rounded-full transition-[width,background-color] duration-base ease-standard ${barColor}`}
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}

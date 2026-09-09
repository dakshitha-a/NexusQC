// Shared storage-display helpers for the admin console.
//
// These started out local to AdminPanel.tsx. They were lifted here when
// UsersSection needed the same bar: importing them back out of AdminPanel
// would have made AdminPanel and its own child sections a circular import.

// Decimal gigabytes (1000^3), matching StorageUsageBadge.tsx -- consistent
// with how the quota numbers this panel edits are described everywhere else
// in the app.
export function formatGB(bytes: number): string {
  const gb = bytes / 1_000_000_000;
  return `${gb < 10 ? gb.toFixed(2) : gb.toFixed(1)} GB`;
}

// Scales to the magnitude, unlike formatGB above. Quota figures are always
// gigabytes and read best fixed at that unit; incidental sizes -- a handful
// of orphaned directories, say -- are usually kilobytes, where "0.00 GB"
// tells the reader nothing about whether it is worth reclaiming.
export function formatBytes(bytes: number): string {
  if (bytes < 1000) return `${bytes} B`;
  const units = ["kB", "MB", "GB", "TB"];
  let value = bytes / 1000;
  let unit = 0;
  while (value >= 1000 && unit < units.length - 1) {
    value /= 1000;
    unit += 1;
  }
  return `${value < 10 ? value.toFixed(1) : Math.round(value)} ${units[unit]}`;
}

export function UsageBar({ used, quota }: { used: number; quota: number }) {
  const pct = quota > 0 ? Math.min(100, (used / quota) * 100) : 0;
  const barColor = pct >= 95 ? "bg-status-failed" : pct >= 80 ? "bg-status-running" : "bg-accent";
  return (
    <div className="flex items-center gap-2">
      <div className="h-1.5 w-24 overflow-hidden rounded-full bg-surface-raised">
        <div
          className={`h-full rounded-full transition-[width,background-color] duration-base ease-standard ${barColor}`}
          style={{ width: `${pct}%` }}
        />
      </div>
      <span className="text-2xs tabular-nums text-text-muted">
        {formatGB(used)} / {formatGB(quota)}
      </span>
    </div>
  );
}

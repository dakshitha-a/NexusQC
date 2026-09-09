/**
 * How long ago, in the shortest form that still says something useful.
 *
 * This lived as four separate copies -- JobManagerPanel, JobsPanel,
 * PlotsPanel and ConversationList -- three of them byte-identical and the
 * fourth differing only in that it had no null guard and no sub-minute step,
 * so a conversation touched twenty seconds ago read "just now" while a job in
 * the same state read "20s ago". One copy, one wording.
 */
export function relativeTime(epochSeconds: number | null): string {
  if (!epochSeconds) return "";
  const diffSec = Date.now() / 1000 - epochSeconds;
  if (diffSec < 5) return "now";
  if (diffSec < 60) return `${Math.floor(diffSec)}s ago`;
  if (diffSec < 3600) return `${Math.floor(diffSec / 60)}m ago`;
  if (diffSec < 86400) return `${Math.floor(diffSec / 3600)}h ago`;
  return `${Math.floor(diffSec / 86400)}d ago`;
}

/** One absolute timestamp in the viewer's own locale, or "" for a missing one. */
export function absoluteTime(epochSeconds: number | null): string {
  if (!epochSeconds) return "";
  return new Date(epochSeconds * 1000).toLocaleString();
}

/**
 * The hover text behind a job row's relative time.
 *
 * The visible number is `updated_at`, i.e. last activity, because that is what
 * "ago" means to somebody waiting on a job. But the Job Manager's list is
 * sorted newest-`created_at`-first server-side, so an old job that finished
 * recently shows a fresh time part-way down the list. Naming both stamps here
 * is what resolves that, and it costs a row nothing because it is a title.
 */
export function jobTimeTitle(job: { created_at: number | null; updated_at: number | null }): string {
  const parts: string[] = [];
  if (job.updated_at) parts.push(`Last activity ${absoluteTime(job.updated_at)}`);
  if (job.created_at) parts.push(`Submitted ${absoluteTime(job.created_at)}`);
  return parts.join("\n");
}

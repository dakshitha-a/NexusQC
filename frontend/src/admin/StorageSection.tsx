import { Eraser, RefreshCw } from "lucide-react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import * as api from "../lib/api";
import { ConfirmButton } from "./ConfirmButton";
import { formatBytes, formatGB, UsageBar } from "./usage";
import { useSortableRows } from "./useSortableRows";

const ACCESSORS = {
  username: (r: api.AdminUserUsage) => r.username,
  kb: (r: api.AdminUserUsage) => r.kb_bytes,
  jobs: (r: api.AdminUserUsage) => r.jobs_and_chat_bytes,
  total: (r: api.AdminUserUsage) => r.total_bytes,
};

/** Job directories with no spec.json.
 *
 * They are invisible everywhere else in the app: app/chemistry/jobs/quota.py's
 * _iter_job_ids() requires spec.json, so nothing lists these, nothing purges
 * them on its own, and they count toward nobody's quota. This block is the
 * only place they surface, which is the whole point -- an admin cannot act on
 * disk they cannot see.
 *
 * It lives in Storage rather than the danger zone deliberately. The danger
 * zone's actions destroy a category of real user data across the whole
 * deployment and are gated behind typing a phrase; this one destroys nothing
 * anybody owns, and putting it there would both overweight it and dilute the
 * signal that everything in that section is irreversible.
 */
function OrphanedDirectories({ report }: { report: api.AdminStorageReport["orphaned_jobs"] }) {
  const queryClient = useQueryClient();
  const purge = useMutation({
    mutationFn: api.purgeOrphanedJobs,
    onSettled: () => queryClient.invalidateQueries({ queryKey: ["admin", "storage"] }),
  });

  const count = report.job_ids.length;
  if (count === 0 && report.held_back === 0) {
    return (
      <div className="mb-2 text-2xs text-text-muted" data-testid="admin-orphans-none">
        No orphaned job directories.
      </div>
    );
  }

  return (
    <div className="mb-2 rounded border border-border px-3 py-2.5" data-testid="admin-orphans">
      <div className="flex items-start gap-2">
        <Eraser size={14} className="mt-0.5 shrink-0 text-text-muted" />
        <div className="min-w-0 flex-1">
          <div className="text-xs font-medium text-text">
            {count === 0
              ? "No orphaned job directories can be reclaimed yet"
              : `${count} orphaned job ${count === 1 ? "directory" : "directories"} · ${formatBytes(report.bytes)}`}
          </div>
          <div className="mt-0.5 text-2xs text-text-muted">
            Directories left behind without a job record. An interrupted delete, or an artifact written after
            its job was purged. Nothing lists them and they count toward nobody's quota, so nothing reclaims
            them on its own.
          </div>
          {report.held_back > 0 && (
            // Said out loud rather than quietly subtracted: a button that
            // removes fewer than the number printed next to it is the exact
            // shape of the bug this area already had once.
            <div className="mt-1 text-2xs text-text-muted" data-testid="admin-orphans-held-back">
              {report.held_back} more {report.held_back === 1 ? "was" : "were"} found but changed too recently to
              be safely removed, a job being submitted looks the same for a moment. {report.held_back === 1 ? "It" : "They"}{" "}
              can be reclaimed after an hour of no activity.
            </div>
          )}
          {purge.isError && (
            <div className="mt-1 text-2xs text-status-failed">Purge failed: {String(purge.error)}</div>
          )}
          {count > 0 && (
            <div className="mt-2" data-testid="admin-purge-orphans-wrap">
              <ConfirmButton
                label="Reclaim"
                confirmLabel="Reclaim"
                warning={`Permanently deletes ${count} orphaned ${
                  count === 1 ? "directory" : "directories"
                } from disk. No job, conversation or upload is affected.`}
                onConfirm={() => purge.mutate()}
                pending={purge.isPending}
              />
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export function StorageSection() {
  const queryClient = useQueryClient();
  // Live readout, per the deployment requirement -- refetches on an interval
  // while the panel is open rather than only on mount, and gets invalidated
  // immediately after any purge so the numbers never look stale right after
  // an action the admin just took.
  const storageQuery = useQuery({
    queryKey: ["admin", "storage"],
    queryFn: api.getAdminStorage,
    refetchInterval: 15_000,
  });
  const storage = storageQuery.data;
  // Biggest consumer first: the reason to open this section is almost always
  // "who is using all the space".
  const { rows, header } = useSortableRows(storage?.per_user ?? [], ACCESSORS, "total");

  return (
    <section>
      <div className="mb-1.5 flex items-center justify-between">
        <h3 className="text-xs font-semibold uppercase tracking-wide text-text-muted">Live storage usage</h3>
        <button
          onClick={() => queryClient.invalidateQueries({ queryKey: ["admin", "storage"] })}
          className="flex items-center gap-1 text-2xs text-text-muted hover:text-text"
        >
          <RefreshCw size={11} /> Refresh
        </button>
      </div>
      {!storage ? (
        <div className="text-xs text-text-muted">Loading...</div>
      ) : (
        <>
          <div className="mb-2 rounded border border-border px-3 py-2.5">
            <div className="mb-1 text-xs font-medium text-text">
              Global total ({formatGB(storage.global.total_bytes)} of {formatGB(storage.global.quota_bytes)})
            </div>
            <UsageBar used={storage.global.total_bytes} quota={storage.global.quota_bytes} />
            <div className="mt-1 text-2xs text-text-muted">
              KB {formatGB(storage.global.kb_bytes)} · Jobs {formatGB(storage.global.job_bytes)} · Chat{" "}
              {formatGB(storage.global.chat_bytes)}
            </div>
          </div>
          <OrphanedDirectories report={storage.orphaned_jobs} />
          <div className="overflow-x-auto rounded border border-border">
            <table className="w-full text-left text-2xs">
              <thead className="border-b border-border text-text-muted">
                <tr>
                  {header("User", "username")}
                  {header("KB", "kb")}
                  {header("Jobs + chat", "jobs")}
                  {header("Total", "total")}
                </tr>
              </thead>
              <tbody>
                {rows.length === 0 && (
                  <tr>
                    <td colSpan={4} className="px-2 py-3 text-center text-text-muted">
                      No users yet.
                    </td>
                  </tr>
                )}
                {rows.map((row) => (
                  <tr key={row.user_id} className="border-b border-border last:border-b-0">
                    <td className="px-2 py-1.5 text-text">{row.username}</td>
                    <td className="px-2 py-1.5">
                      <UsageBar used={row.kb_bytes} quota={row.kb_quota_bytes} />
                    </td>
                    <td className="px-2 py-1.5">
                      <UsageBar used={row.jobs_and_chat_bytes} quota={row.jobs_and_chat_quota_bytes} />
                    </td>
                    <td className="px-2 py-1.5 tabular-nums text-text-muted">{formatGB(row.total_bytes)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </section>
  );
}

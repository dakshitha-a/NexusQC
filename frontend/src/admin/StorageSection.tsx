import { RefreshCw } from "lucide-react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import * as api from "../lib/api";
import { formatGB, UsageBar } from "./usage";
import { useSortableRows } from "./useSortableRows";

const ACCESSORS = {
  username: (r: api.AdminUserUsage) => r.username,
  kb: (r: api.AdminUserUsage) => r.kb_bytes,
  jobs: (r: api.AdminUserUsage) => r.jobs_and_chat_bytes,
  total: (r: api.AdminUserUsage) => r.total_bytes,
};

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
          className="flex items-center gap-1 text-[11px] text-text-muted hover:text-text"
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
            <div className="mt-1 text-[11px] text-text-muted">
              KB {formatGB(storage.global.kb_bytes)} · Jobs {formatGB(storage.global.job_bytes)} · Chat{" "}
              {formatGB(storage.global.chat_bytes)}
            </div>
          </div>
          <div className="overflow-x-auto rounded border border-border">
            <table className="w-full text-left text-[11px]">
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

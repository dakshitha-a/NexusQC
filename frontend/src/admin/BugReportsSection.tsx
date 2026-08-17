import { useMutation, useQuery } from "@tanstack/react-query";
import * as api from "../lib/api";

/**
 * The admin side of bug reports.
 *
 * POST /api/bug-reports and GET/PATCH /api/admin/bug-reports have all
 * existed and worked for some time with no UI on either end, so reports
 * could be neither filed nor read. The filing half lives in the account
 * flyout; this is the inbox.
 */
export function BugReportsSection({
  onMutationSuccess,
  onMutationError,
}: {
  onMutationSuccess: () => void;
  onMutationError: (error: unknown) => void;
}) {
  const reportsQuery = useQuery({
    queryKey: ["admin", "bug-reports"],
    queryFn: api.listAdminBugReports,
  });

  const statusMutation = useMutation({
    mutationFn: ({ id, status }: { id: string; status: "open" | "closed" }) =>
      api.setAdminBugReportStatus(id, status),
    onSuccess: onMutationSuccess,
    onError: onMutationError,
  });

  const rows = reportsQuery.data ?? [];
  const openCount = rows.filter((r) => r.status === "open").length;

  return (
    <section className="mb-5">
      <h3 className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-text-muted">
        Bug reports{openCount > 0 ? ` (${openCount} open)` : ""}
      </h3>
      <div className="overflow-x-auto rounded border border-border">
        <table className="w-full text-left text-[11px]">
          <thead className="border-b border-border text-text-muted">
            <tr>
              <th className="px-2 py-1.5 font-medium">Status</th>
              <th className="px-2 py-1.5 font-medium">Reported</th>
              <th className="px-2 py-1.5 font-medium">Report</th>
              <th className="px-2 py-1.5 font-medium">Actions</th>
            </tr>
          </thead>
          <tbody>
            {reportsQuery.isLoading && (
              <tr>
                <td colSpan={4} className="px-2 py-3 text-center text-text-muted">
                  Loading...
                </td>
              </tr>
            )}
            {!reportsQuery.isLoading && rows.length === 0 && (
              <tr>
                <td colSpan={4} className="px-2 py-3 text-center text-text-muted">
                  No bug reports.
                </td>
              </tr>
            )}
            {rows.map((row) => (
              <tr key={row.id} className="border-b border-border last:border-b-0">
                <td
                  className={`px-2 py-1.5 font-medium ${
                    row.status === "open" ? "text-status-running" : "text-text-muted"
                  }`}
                >
                  {row.status}
                </td>
                <td className="whitespace-nowrap px-2 py-1.5 text-text-muted">
                  {new Date(row.created_at).toLocaleString()}
                </td>
                <td className="px-2 py-1.5 text-text">
                  <div className="max-w-md whitespace-pre-wrap break-words">{row.body}</div>
                </td>
                <td className="px-2 py-1.5">
                  <button
                    onClick={() =>
                      statusMutation.mutate({
                        id: row.id,
                        status: row.status === "open" ? "closed" : "open",
                      })
                    }
                    disabled={statusMutation.isPending}
                    className="rounded border border-border px-2 py-0.5 text-[11px] text-text-muted hover:bg-surface-raised hover:text-text disabled:opacity-30"
                  >
                    {row.status === "open" ? "Close" : "Reopen"}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

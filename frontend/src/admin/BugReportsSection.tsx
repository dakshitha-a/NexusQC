import { useState } from "react";
import { Archive, ArchiveRestore, Paperclip } from "lucide-react";
import { useMutation, useQuery } from "@tanstack/react-query";
import * as api from "../lib/api";
import type { AdminBugReport } from "../lib/api";
import { ConfirmButton } from "./ConfirmButton";
import { DetailField, ExpandableRow } from "./ExpandableRow";
import { useSortableRows } from "./useSortableRows";

const ACCESSORS = {
  status: (r: AdminBugReport) => (r.archived_at ? "archived" : r.status),
  reported: (r: AdminBugReport) => r.created_at,
  reporter: (r: AdminBugReport) => r.reporter_username,
};

/** First line, or the first ~90 characters -- enough to tell two reports
 *  apart in a list without turning a row into a wall of text. */
function preview(body: string): string {
  const firstLine = body.split("\n").find((l) => l.trim().length > 0) ?? "";
  return firstLine.length > 90 ? `${firstLine.slice(0, 90)}…` : firstLine;
}

/**
 * The admin side of bug reports.
 *
 * The body used to render in full inside a `max-w-md` table cell at 11px, so a
 * long report was an unreadable slab inside one row and there was no way to
 * see anything else while it was there -- no truncation, but no expand
 * affordance either. It also showed no reporter at all, because the query
 * behind it never joined to users.
 *
 * Now: one-line preview per row, full body and screenshots on expansion, and
 * archive/delete alongside the existing open/closed toggle.
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
  const [openId, setOpenId] = useState<string | null>(null);
  const [showArchived, setShowArchived] = useState(false);
  const [lightbox, setLightbox] = useState<string | null>(null);

  const patchMutation = useMutation({
    mutationFn: ({ id, patch }: { id: string; patch: { status?: "open" | "closed"; archived?: boolean } }) =>
      api.patchAdminBugReport(id, patch),
    onSuccess: onMutationSuccess,
    onError: onMutationError,
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => api.deleteAdminBugReport(id),
    onSuccess: onMutationSuccess,
    onError: onMutationError,
  });

  const all = reportsQuery.data ?? [];
  const filtered = showArchived ? all : all.filter((r) => !r.archived_at);
  const { rows, header } = useSortableRows(filtered, ACCESSORS, "reported");
  // Archived reports are excluded on purpose: archiving a stale report has to
  // clear it from the count, or the badge stays stuck and archiving achieves
  // nothing an admin can see.
  const openCount = all.filter((r) => r.status === "open" && !r.archived_at).length;
  const archivedCount = all.filter((r) => r.archived_at).length;

  return (
    <section>
      <div className="mb-1.5 flex items-center justify-between">
        <h3 className="text-xs font-semibold uppercase tracking-wide text-text-muted">
          Bug reports{openCount > 0 ? ` (${openCount} open)` : ""}
        </h3>
        <label className="flex items-center gap-1.5 text-2xs text-text-muted">
          <input
            type="checkbox"
            checked={showArchived}
            data-testid="admin-reports-show-archived"
            onChange={(e) => setShowArchived(e.target.checked)}
          />
          Include archived{archivedCount > 0 ? ` (${archivedCount})` : ""}
        </label>
      </div>
      <div className="mb-1.5 text-2xs text-text-muted">
        Click a report for its full text and any screenshots the reporter attached.
      </div>

      <div className="overflow-x-auto rounded border border-border">
        <table className="w-full text-left text-2xs">
          <thead className="border-b border-border text-text-muted">
            <tr>
              <th className="w-5" />
              {header("Status", "status")}
              {header("Reported", "reported", "whitespace-nowrap")}
              {header("By", "reporter")}
              {header("Report")}
            </tr>
          </thead>
          <tbody>
            {reportsQuery.isLoading && (
              <tr>
                <td colSpan={5} className="px-2 py-3 text-center text-text-muted">
                  Loading...
                </td>
              </tr>
            )}
            {!reportsQuery.isLoading && rows.length === 0 && (
              <tr>
                <td colSpan={5} className="px-2 py-3 text-center text-text-muted">
                  {all.length === 0 ? "No bug reports." : "No unarchived bug reports."}
                </td>
              </tr>
            )}
            {rows.map((row) => (
              <ExpandableRow
                key={row.id}
                testId={`admin-report-row-${row.id}`}
                expanded={openId === row.id}
                onToggle={() => setOpenId(openId === row.id ? null : row.id)}
                tone={row.archived_at ? "opacity-60" : undefined}
                cells={[
                  <span
                    key="status"
                    className={`font-medium ${
                      row.archived_at
                        ? "text-text-muted"
                        : row.status === "open"
                          ? "text-status-running"
                          : "text-text-muted"
                    }`}
                  >
                    {row.archived_at ? "archived" : row.status}
                  </span>,
                  <span key="when" className="whitespace-nowrap text-text-muted">
                    {new Date(row.created_at).toLocaleString()}
                  </span>,
                  <span key="who" className="text-text-muted">
                    {row.reporter_username ?? <span className="italic">deleted user</span>}
                  </span>,
                  <span key="body" className="flex items-center gap-1.5 text-text">
                    {row.attachments.length > 0 && (
                      <Paperclip size={10} className="shrink-0 text-text-muted" />
                    )}
                    <span className="min-w-0 truncate">{preview(row.body)}</span>
                  </span>,
                ]}
                detail={
                  <div>
                    <DetailField label="Reported by">
                      {row.reporter_username ?? "deleted user"}
                    </DetailField>
                    <DetailField label="Reported">
                      {new Date(row.created_at).toLocaleString()}
                    </DetailField>
                    <DetailField label="Status">
                      {row.status}
                      {row.archived_at &&
                        ` · archived ${new Date(row.archived_at).toLocaleString()}`}
                    </DetailField>

                    <div className="mt-2">
                      <div className="mb-1 text-text-muted">Report</div>
                      <div
                        data-testid="admin-report-body"
                        className="max-h-80 overflow-y-auto whitespace-pre-wrap break-words rounded border border-border bg-bg p-2.5 text-xs leading-relaxed text-text"
                      >
                        {row.body}
                      </div>
                    </div>

                    {row.attachments.length > 0 && (
                      <div className="mt-2">
                        <div className="mb-1 text-text-muted">
                          Screenshots ({row.attachments.length})
                        </div>
                        <div className="flex flex-wrap gap-2">
                          {row.attachments.map((a) => (
                            <button
                              key={a.id}
                              type="button"
                              onClick={() => setLightbox(api.bugAttachmentUrl(a.id))}
                              title={`${a.original_name}. Click to enlarge`}
                              className="rounded border border-border hover:border-accent"
                            >
                              <img
                                src={api.bugAttachmentUrl(a.id)}
                                alt={a.original_name}
                                data-testid="admin-report-attachment"
                                className="size-24 rounded object-cover"
                              />
                            </button>
                          ))}
                        </div>
                      </div>
                    )}

                    <div className="mt-3 flex flex-wrap items-start gap-2 border-t border-border pt-2">
                      <button
                        onClick={() =>
                          patchMutation.mutate({
                            id: row.id,
                            patch: { status: row.status === "open" ? "closed" : "open" },
                          })
                        }
                        disabled={patchMutation.isPending}
                        className="rounded border border-border px-2 py-0.5 text-2xs text-text-muted hover:bg-surface-raised hover:text-text disabled:opacity-30"
                      >
                        {row.status === "open" ? "Close" : "Reopen"}
                      </button>
                      <button
                        onClick={() =>
                          patchMutation.mutate({
                            id: row.id,
                            patch: { archived: !row.archived_at },
                          })
                        }
                        disabled={patchMutation.isPending}
                        data-testid="admin-report-archive"
                        className="flex items-center gap-1 rounded border border-border px-2 py-0.5 text-2xs text-text-muted hover:bg-surface-raised hover:text-text disabled:opacity-30"
                      >
                        {row.archived_at ? <ArchiveRestore size={11} /> : <Archive size={11} />}
                        {row.archived_at ? "Unarchive" : "Archive"}
                      </button>
                      <ConfirmButton
                        label="Delete report"
                        confirmLabel="Delete report"
                        warning="Permanently deletes this report and any screenshots attached to it, from the database and from disk. Archive it instead if you only want it out of the list."
                        pending={deleteMutation.isPending}
                        onConfirm={() => deleteMutation.mutate(row.id)}
                      />
                    </div>
                  </div>
                }
              />
            ))}
          </tbody>
        </table>
      </div>

      {/* Deliberately not a Radix dialog: this sits inside the admin console,
          which is already one, and nesting a modal in a modal makes Escape
          ambiguous. A plain overlay dismissed by any click is enough for
          "show me that screenshot bigger". */}
      {lightbox && (
        <div
          onClick={() => setLightbox(null)}
          className="fixed inset-0 z-[70] flex items-center justify-center bg-black/80 p-8 animate-fade-in"
        >
          <img src={lightbox} alt="Screenshot" className="max-h-full max-w-full object-contain" />
        </div>
      )}
    </section>
  );
}

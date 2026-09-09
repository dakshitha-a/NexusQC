import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import * as api from "../lib/api";
import { DetailField, ExpandableRow } from "./ExpandableRow";
import { useSortableRows } from "./useSortableRows";

const ACCESSORS = {
  when: (r: api.AdminAuditLogEntry) => r.created_at,
  action: (r: api.AdminAuditLogEntry) => r.action,
  target: (r: api.AdminAuditLogEntry) => r.target,
};

/**
 * The admin action history.
 *
 * Two things were wrong with how this read. The target was hard-truncated
 * (`max-w-xs truncate`) with a title attribute as the only way to recover it,
 * which is unusable for the job/user ids that make up most targets. And
 * `details` -- a JSONB column carrying what actually changed, which is the
 * interesting part of any config change -- was fetched by the query, typed on
 * AdminAuditLogEntry, and then rendered nowhere at all.
 *
 * Both now live in the expanded row. The log stays append-only and
 * database-enforced; nothing here can edit it.
 */
export function AuditSection() {
  const auditQuery = useQuery({ queryKey: ["admin", "audit-log"], queryFn: api.getAdminAuditLog });
  const [openId, setOpenId] = useState<string | null>(null);
  const { rows, header } = useSortableRows(auditQuery.data ?? [], ACCESSORS, "when");

  return (
    <section>
      <h3 className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-text-muted">
        Admin action history
      </h3>
      <div className="mb-1.5 text-2xs text-text-muted">
        Append-only -- config changes, purges, user and report actions are recorded here and cannot be
        edited or deleted by any admin, including at the database level. Click a row for its full target and
        details.
      </div>
      <div className="overflow-x-auto rounded border border-border">
        <table className="w-full text-left text-2xs">
          <thead className="border-b border-border text-text-muted">
            <tr>
              <th className="w-5" />
              {header("When", "when", "whitespace-nowrap")}
              {header("Action", "action")}
              {header("Target", "target")}
            </tr>
          </thead>
          <tbody>
            {(rows ?? []).length === 0 && (
              <tr>
                <td colSpan={4} className="px-2 py-3 text-center text-text-muted">
                  No admin actions recorded yet.
                </td>
              </tr>
            )}
            {rows.map((row) => (
              <ExpandableRow
                key={row.id}
                expanded={openId === row.id}
                onToggle={() => setOpenId(openId === row.id ? null : row.id)}
                cells={[
                  <span key="when" className="whitespace-nowrap text-text-muted">
                    {new Date(row.created_at).toLocaleString()}
                  </span>,
                  <span key="action" className="text-text">{row.action}</span>,
                  <span key="target" className="block max-w-xs truncate font-mono text-text-muted">
                    {row.target ?? "--"}
                  </span>,
                ]}
                detail={
                  <div>
                    <DetailField label="Action">{row.action}</DetailField>
                    <DetailField label="When">{new Date(row.created_at).toLocaleString()}</DetailField>
                    <DetailField label="Target">
                      <span className="font-mono">{row.target ?? "--"}</span>
                    </DetailField>
                    {/* Both, not one or the other. The username is what a
                        reader recognises and it survives the account being
                        deleted (it is captured when the row is written, and
                        this table has no foreign key to users); the id is
                        what distinguishes two accounts that reused a name. */}
                    <DetailField label="Actor">
                      {row.actor_username ?? (row.actor_user_id ? "unknown user" : "system")}
                    </DetailField>
                    <DetailField label="Actor user id">
                      <span className="font-mono">{row.actor_user_id ?? "--"}</span>
                    </DetailField>
                    <DetailField label="Details">
                      {row.details && Object.keys(row.details).length > 0 ? (
                        <pre className="max-h-56 overflow-auto rounded border border-border bg-bg p-2 font-mono text-2xs text-text-muted">
                          {JSON.stringify(row.details, null, 2)}
                        </pre>
                      ) : (
                        <span className="text-text-muted">none recorded</span>
                      )}
                    </DetailField>
                  </div>
                }
              />
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

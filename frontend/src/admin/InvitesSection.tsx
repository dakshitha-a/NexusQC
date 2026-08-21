import { Copy, Check } from "lucide-react";
import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import * as api from "../lib/api";
import type { AdminInviteRow } from "../lib/api";
import { ConfirmButton } from "./ConfirmButton";
import { DetailField, ExpandableRow } from "./ExpandableRow";
import { useSortableRows } from "./useSortableRows";

type InviteStatus = "redeemed" | "revoked" | "expired" | "pending";

/**
 * Status is derived, never stored -- the table has no status column, only
 * the three timestamps and expires_at.
 *
 * Evaluation order matters. Redeemed is checked first because a redeemed
 * invite can never be revoked (the route refuses it), so a row carrying
 * both can only come from data written before that guard existed, and
 * "redeemed" is the truthful thing to show: the account exists either way.
 */
export function inviteStatus(row: AdminInviteRow): InviteStatus {
  if (row.redeemed_at) return "redeemed";
  if (row.revoked_at) return "revoked";
  if (new Date(row.expires_at) <= new Date()) return "expired";
  return "pending";
}

const STATUS_CLASS: Record<InviteStatus, string> = {
  redeemed: "text-status-completed",
  revoked: "text-status-failed",
  expired: "text-text-muted",
  pending: "text-status-running",
};

const ACCESSORS = {
  status: (r: AdminInviteRow) => inviteStatus(r),
  role: (r: AdminInviteRow) => r.role,
  created: (r: AdminInviteRow) => r.created_at,
  expires: (r: AdminInviteRow) => r.expires_at,
  redeemed_by: (r: AdminInviteRow) => r.redeemed_by_username,
};

// Renders "username (First Last)" when a name is on file, or just the
// username otherwise -- the invite may have been created/redeemed before
// first/last name existed, so the name half is always optional.
function formatPerson(
  username: string | null,
  firstName: string | null,
  lastName: string | null,
): string {
  if (!username) return "--";
  const name = `${firstName ?? ""} ${lastName ?? ""}`.trim();
  return name ? `${username} (${name})` : username;
}

function inviteLink(token: string): string {
  // The shape LoginScreen.tsx actually parses: a bare ?invite= query param
  // flips the form into register mode and prefills the token. There is no
  // router in this app, so this is the whole deep-link contract.
  return `${window.location.origin}/?invite=${token}`;
}

function CopyLinkButton({ token }: { token: string }) {
  const [copied, setCopied] = useState(false);
  const [fallback, setFallback] = useState<string | null>(null);
  const link = inviteLink(token);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(link);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // Both nginx listeners are HTTPS so the clipboard API has a secure
      // context, but permission is still deniable and a headless browser
      // does not grant it by default -- an unhandled rejection here would
      // leave the admin with no way to get the link at all.
      setFallback(link);
    }
  };

  if (fallback) {
    return (
      <input
        readOnly
        value={fallback}
        onFocus={(e) => e.currentTarget.select()}
        autoFocus
        className="w-56 rounded border border-border bg-surface-raised px-1.5 py-0.5 text-[10px] text-text"
      />
    );
  }

  return (
    <button
      onClick={copy}
      title={link}
      className="inline-flex items-center gap-1 rounded border border-border px-2 py-0.5 text-[11px] text-text-muted hover:bg-surface-raised hover:text-text"
    >
      {copied ? <Check size={11} /> : <Copy size={11} />}
      {copied ? "Copied" : "Copy link"}
    </button>
  );
}

export function InvitesSection({
  onMutationSuccess,
  onMutationError,
}: {
  onMutationSuccess: () => void;
  onMutationError: (error: unknown) => void;
}) {
  const invitesQuery = useQuery({ queryKey: ["admin", "invites"], queryFn: api.listAdminInvites });

  const [role, setRole] = useState<"user" | "admin">("user");
  const [emailHint, setEmailHint] = useState("");
  const [ttlHours, setTtlHours] = useState(72);
  const [justCreated, setJustCreated] = useState<string | null>(null);
  const [hideInactive, setHideInactive] = useState(false);
  const [openToken, setOpenToken] = useState<string | null>(null);

  const createMutation = useMutation({
    mutationFn: () => api.createAdminInvite(role, emailHint.trim() || null, ttlHours),
    onSuccess: (row) => {
      setJustCreated(row.token);
      setEmailHint("");
      onMutationSuccess();
    },
    onError: onMutationError,
  });

  const revokeMutation = useMutation({
    mutationFn: (token: string) => api.revokeAdminInvite(token),
    onSuccess: onMutationSuccess,
    onError: onMutationError,
  });

  const allRows = invitesQuery.data ?? [];
  // Invites are never deleted (revocation is a soft flag), so this table only
  // ever grows. The filter is cheap now and awkward to retrofit once an admin
  // has hundreds of spent rows.
  const filtered = hideInactive ? allRows.filter((r) => inviteStatus(r) === "pending") : allRows;
  // Default matches the server's own `ORDER BY t.created_at DESC`, so the
  // first render does not visibly reshuffle what the API just returned.
  const { rows, header } = useSortableRows(filtered, ACCESSORS, "created");

  return (
    <section>
      <div className="mb-1.5 flex items-center justify-between">
        <h3 className="text-xs font-semibold uppercase tracking-wide text-text-muted">Invites</h3>
        <label className="flex items-center gap-1.5 text-[11px] text-text-muted">
          <input
            type="checkbox"
            checked={hideInactive}
            onChange={(e) => setHideInactive(e.target.checked)}
          />
          Only unredeemed
        </label>
      </div>

      <div className="mb-2 flex flex-wrap items-center gap-2 rounded border border-border px-3 py-2">
        <select
          value={role}
          onChange={(e) => setRole(e.target.value as "user" | "admin")}
          className="rounded border border-border bg-surface-raised px-2 py-1 text-[11px] text-text"
        >
          <option value="user">user</option>
          <option value="admin">admin</option>
        </select>
        <input
          type="email"
          value={emailHint}
          onChange={(e) => setEmailHint(e.target.value)}
          placeholder="Email hint (optional)"
          className="min-w-0 flex-1 rounded border border-border bg-surface-raised px-2 py-1 text-[11px] text-text placeholder:text-text-muted"
        />
        <input
          type="number"
          min={1}
          value={ttlHours}
          onChange={(e) => setTtlHours(Number(e.target.value))}
          className="w-16 rounded border border-border bg-surface-raised px-2 py-1 text-[11px] text-text"
        />
        <span className="text-[11px] text-text-muted">hours</span>
        <button
          onClick={() => createMutation.mutate()}
          disabled={createMutation.isPending}
          className="rounded bg-accent px-2 py-1 text-[11px] font-medium text-white disabled:opacity-30"
        >
          {createMutation.isPending ? "Creating..." : "Create invite"}
        </button>
      </div>

      {justCreated && (
        <div className="mb-2 flex items-center gap-2 rounded border border-accent/40 bg-accent/5 px-3 py-2 text-[11px]">
          <span className="shrink-0 font-medium text-text">New invite link</span>
          <input
            readOnly
            value={inviteLink(justCreated)}
            onFocus={(e) => e.currentTarget.select()}
            className="min-w-0 flex-1 rounded border border-border bg-surface-raised px-1.5 py-0.5 text-[10px] text-text"
          />
          <CopyLinkButton token={justCreated} />
          <button
            onClick={() => setJustCreated(null)}
            className="shrink-0 text-text-muted hover:text-text"
          >
            Dismiss
          </button>
        </div>
      )}

      <div className="overflow-x-auto rounded border border-border">
        <table className="w-full text-left text-[11px]">
          <thead className="border-b border-border text-text-muted">
            <tr>
              <th className="w-5" />
              {header("Status", "status")}
              {header("Role", "role")}
              {header("Created", "created", "whitespace-nowrap")}
              {header("Email hint")}
              {header("Expires", "expires", "whitespace-nowrap")}
              {header("Redeemed by", "redeemed_by")}
            </tr>
          </thead>
          <tbody>
            {invitesQuery.isLoading && (
              <tr>
                <td colSpan={7} className="px-2 py-3 text-center text-text-muted">
                  Loading...
                </td>
              </tr>
            )}
            {!invitesQuery.isLoading && rows.length === 0 && (
              <tr>
                <td colSpan={7} className="px-2 py-3 text-center text-text-muted">
                  No invites yet.
                </td>
              </tr>
            )}
            {rows.map((row) => {
              const status = inviteStatus(row);
              return (
                <ExpandableRow
                  key={row.token}
                  expanded={openToken === row.token}
                  onToggle={() => setOpenToken(openToken === row.token ? null : row.token)}
                  tone={status === "pending" ? undefined : "opacity-60"}
                  cells={[
                    <span key="status" className={`font-medium ${STATUS_CLASS[status]}`}>{status}</span>,
                    <span key="role" className="text-text">{row.role}</span>,
                    <span key="created" className="whitespace-nowrap text-text-muted">
                      {new Date(row.created_at).toLocaleString()}
                    </span>,
                    <span key="hint" className="text-text-muted">{row.email_hint ?? "--"}</span>,
                    <span key="expires" className="whitespace-nowrap text-text-muted">
                      {new Date(row.expires_at).toLocaleString()}
                    </span>,
                    <span key="redeemed" className="text-text-muted">
                      {formatPerson(row.redeemed_by_username, row.redeemed_by_first_name, row.redeemed_by_last_name)}
                    </span>,
                  ]}
                  detail={
                    <div>
                      {/* The raw token is deliberately NOT rendered, collapsed
                          or expanded. ui_04_admin_visual.spec.mjs screenshots
                          this console, and scripts/check_public_safe.sh cannot
                          read images -- so a live token reaching a committed
                          PNG is a permanent leak that nothing downstream
                          catches. Copy link carries the real value. */}
                      <DetailField label="Token">
                        <span className="font-mono">{row.token.slice(0, 8)}…</span>
                        <span className="ml-2 text-text-muted">
                          (not shown in full — use Copy link)
                        </span>
                      </DetailField>
                      <DetailField label="Status">{status}</DetailField>
                      <DetailField label="Role">{row.role}</DetailField>
                      <DetailField label="Email hint">{row.email_hint ?? "--"}</DetailField>
                      <DetailField label="Created">
                        {new Date(row.created_at).toLocaleString()}
                      </DetailField>
                      <DetailField label="Created by">
                        {formatPerson(row.created_by_username, row.created_by_first_name, row.created_by_last_name)}
                      </DetailField>
                      <DetailField label="Expires">
                        {new Date(row.expires_at).toLocaleString()}
                      </DetailField>
                      <DetailField label="Redeemed by">
                        {formatPerson(row.redeemed_by_username, row.redeemed_by_first_name, row.redeemed_by_last_name)}
                        {row.redeemed_at && ` on ${new Date(row.redeemed_at).toLocaleString()}`}
                      </DetailField>
                      {row.revoked_at && (
                        <DetailField label="Revoked">
                          {new Date(row.revoked_at).toLocaleString()}
                        </DetailField>
                      )}
                      {(status === "pending" || status === "expired") && (
                        <div className="mt-2 flex flex-wrap items-start gap-2 border-t border-border pt-2">
                          {status === "pending" && <CopyLinkButton token={row.token} />}
                          <ConfirmButton
                            label="Revoke"
                            confirmLabel="Revoke"
                            warning={
                              status === "pending"
                                ? "This invite can no longer create an account. It stays listed as revoked."
                                : "Marks this expired invite revoked so it is clearly dead."
                            }
                            pending={revokeMutation.isPending}
                            onConfirm={() => revokeMutation.mutate(row.token)}
                          />
                        </div>
                      )}
                    </div>
                  }
                />
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}

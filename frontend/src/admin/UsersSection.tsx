import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import * as api from "../lib/api";
import type { AdminUserRow } from "../lib/api";
import { useAuth } from "../auth/AuthContext";
import { ConfirmButton } from "./ConfirmButton";
import { DetailField, ExpandableRow } from "./ExpandableRow";
import { useSortableRows } from "./useSortableRows";
import { formatGB, UsageBar } from "./usage";

const ACCESSORS = {
  username: (r: AdminUserRow) => r.username,
  role: (r: AdminUserRow) => r.role,
  state: (r: AdminUserRow) => (r.is_active ? "active" : "suspended"),
  created: (r: AdminUserRow) => r.created_at,
  last_login: (r: AdminUserRow) => r.last_login_at,
};

// Same deep-link contract as InvitesSection.inviteLink(): a bare ?reset=
// query param flips LoginScreen into reset mode and prefills the token.
export function resetLink(token: string): string {
  return `${window.location.origin}/?reset=${token}`;
}

/**
 * User management.
 *
 * Suspend, Restore and Delete have always existed and worked. They were
 * invisible: they sat in the last column of an `overflow-x-auto` table inside
 * a dialog narrower than the table, so on any realistic window the Actions
 * column was simply scrolled out of sight -- which is how a working
 * delete-account feature came to be reported as missing. They now live in the
 * expanded row, whose width is the table's width and therefore cannot be
 * pushed off-screen by a long username.
 */
export function UsersSection({
  onMutationSuccess,
  onMutationError,
}: {
  onMutationSuccess: () => void;
  onMutationError: (error: unknown) => void;
}) {
  const { user: me } = useAuth();
  const usersQuery = useQuery({ queryKey: ["admin", "users"], queryFn: api.listAdminUsers });
  // Reuses the same query key the storage section already polls, so this is a
  // cache read rather than a second request.
  const storageQuery = useQuery({ queryKey: ["admin", "storage"], queryFn: api.getAdminStorage });
  const [openId, setOpenId] = useState<string | null>(null);

  const deleteMutation = useMutation({
    mutationFn: (userId: string) => api.deleteAdminUser(userId),
    onSuccess: onMutationSuccess,
    onError: onMutationError,
  });

  const activeMutation = useMutation({
    mutationFn: ({ userId, isActive }: { userId: string; isActive: boolean }) =>
      api.setAdminUserActive(userId, isActive),
    onSuccess: onMutationSuccess,
    onError: onMutationError,
  });

  // The minted token is shown once, here, and never fetched back: the list
  // endpoint deliberately returns the token column, but an admin should be
  // reading the link off the row they just created rather than hunting for
  // it later, and a reset that went astray is revoked and reissued rather
  // than recovered.
  const [freshReset, setFreshReset] = useState<{ userId: string; token: string } | null>(null);
  const resetMutation = useMutation({
    mutationFn: (userId: string) => api.createAdminPasswordReset(userId, 2),
    onSuccess: (row) => {
      setFreshReset({ userId: row.user_id, token: row.token });
      onMutationSuccess();
    },
    onError: onMutationError,
  });

  const { rows, header } = useSortableRows(usersQuery.data ?? [], ACCESSORS, "created");
  // GET /api/admin/storage is served from a short-TTL cache, so a just-deleted
  // user can still appear in per_user for one refresh. The user list is the
  // source of truth for identity; usage is an optional lookup on top of it.
  const usageByUser = new Map((storageQuery.data?.per_user ?? []).map((r) => [r.user_id, r]));

  return (
    <section>
      <h3 className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-text-muted">Users</h3>
      <div className="mb-1.5 text-2xs text-text-muted">
        Click a user for their full record, a password reset, and the suspend, restore and delete actions.
      </div>
      <div className="overflow-x-auto rounded border border-border">
        <table className="w-full text-left text-2xs">
          <thead className="border-b border-border text-text-muted">
            <tr>
              <th className="w-5" />
              {header("User", "username")}
              {header("Role", "role")}
              {header("State", "state")}
              {header("Last login", "last_login")}
              {header("Jobs + chat")}
            </tr>
          </thead>
          <tbody>
            {usersQuery.isLoading && (
              <tr>
                <td colSpan={6} className="px-2 py-3 text-center text-text-muted">
                  Loading...
                </td>
              </tr>
            )}
            {!usersQuery.isLoading && rows.length === 0 && (
              <tr>
                <td colSpan={6} className="px-2 py-3 text-center text-text-muted">
                  No users yet.
                </td>
              </tr>
            )}
            {rows.map((row) => {
              const usage = usageByUser.get(row.id);
              const isSelf = me?.id === row.id;
              return (
                <ExpandableRow
                  key={row.id}
                  testId={`admin-user-row-${row.username}`}
                  expanded={openId === row.id}
                  onToggle={() => setOpenId(openId === row.id ? null : row.id)}
                  tone={row.is_active ? undefined : "opacity-60"}
                  cells={[
                    <span key="user" className="text-text">
                      {row.username}
                      {isSelf && <span className="ml-1.5 text-text-muted">(you)</span>}
                    </span>,
                    <span key="role" className="text-text-muted">{row.role}</span>,
                    <span key="state" className={row.is_active ? "text-status-completed" : "text-status-failed"}>
                      {row.is_active ? "active" : "suspended"}
                    </span>,
                    <span key="login" className="whitespace-nowrap text-text-muted">
                      {row.last_login_at ? new Date(row.last_login_at).toLocaleString() : "never"}
                    </span>,
                    usage ? (
                      <UsageBar key="usage" used={usage.jobs_and_chat_bytes} quota={usage.jobs_and_chat_quota_bytes} />
                    ) : (
                      <span key="usage" className="text-text-muted">--</span>
                    ),
                  ]}
                  detail={
                    <div>
                      <DetailField label="Name">
                        {row.first_name || row.last_name
                          ? `${row.first_name} ${row.last_name}`.trim()
                          : ", "}
                      </DetailField>
                      <DetailField label="Username">{row.username}</DetailField>
                      <DetailField label="Email">{row.email}</DetailField>
                      <DetailField label="User id">
                        <span className="font-mono">{row.id}</span>
                      </DetailField>
                      <DetailField label="Role">{row.role}</DetailField>
                      <DetailField label="Created">
                        {new Date(row.created_at).toLocaleString()}
                      </DetailField>
                      <DetailField label="Last login">
                        {row.last_login_at ? new Date(row.last_login_at).toLocaleString() : "never"}
                      </DetailField>
                      {usage && (
                        <>
                          <DetailField label="Knowledge base">
                            {formatGB(usage.kb_bytes)} of {formatGB(usage.kb_quota_bytes)}
                          </DetailField>
                          <DetailField label="Jobs + chat">
                            {formatGB(usage.jobs_and_chat_bytes)} of{" "}
                            {formatGB(usage.jobs_and_chat_quota_bytes)}
                          </DetailField>
                        </>
                      )}
                      <div className="mt-2 border-t border-border pt-2">
                        {/* Offered for every active account INCLUDING the
                            admin's own: an admin who has forgotten their
                            password but still holds a session is in exactly
                            the position this exists for, and a reset only
                            ever restores access, so there is nothing here to
                            lock anyone out with. Suspended accounts are
                            refused by the server -- restoring one is a
                            separate decision, and a reset must not be a way
                            around it. */}
                        {row.is_active && (
                          <div className="mb-2">
                            <button
                              onClick={() => resetMutation.mutate(row.id)}
                              disabled={resetMutation.isPending}
                              data-testid={`reset-password-${row.username}`}
                              className="rounded border border-border px-2 py-0.5 text-2xs text-text-muted hover:bg-surface-raised hover:text-text disabled:opacity-30"
                            >
                              {resetMutation.isPending ? "Issuing..." : "Issue password reset"}
                            </button>
                            {freshReset?.userId === row.id && (
                              <div
                                data-testid="reset-link-panel"
                                className="mt-2 flex items-center gap-2 rounded border border-accent/40 bg-accent/5 px-2 py-1.5"
                              >
                                <span className="shrink-0 text-2xs font-medium text-text">
                                  Reset link
                                </span>
                                <input
                                  readOnly
                                  value={resetLink(freshReset.token)}
                                  onFocus={(e) => e.currentTarget.select()}
                                  data-testid="reset-link-value"
                                  className="min-w-0 flex-1 rounded border border-border bg-surface-raised px-1.5 py-0.5 text-3xs text-text"
                                />
                                <button
                                  onClick={() => setFreshReset(null)}
                                  className="shrink-0 text-2xs text-text-muted hover:text-text"
                                >
                                  Dismiss
                                </button>
                              </div>
                            )}
                            <div className="mt-1 text-3xs text-text-muted">
                              Single use, valid for 2 hours. Send it to them yourself -- this
                              deployment has no mail server. Using it ends every session the
                              account currently has open.
                            </div>
                          </div>
                        )}
                        {/* The backend refuses self-delete and self-deactivate
                            outright; rendering buttons that can only fail would
                            just be a worse way to learn that. */}
                        {isSelf ? (
                          <span className="text-2xs text-text-muted">
                            This is your own account. Suspending or deleting it is refused by the server --
                            an admin cannot lock themselves out here.
                          </span>
                        ) : (
                          <div className="flex flex-wrap items-start gap-2">
                            {row.is_active ? (
                              <ConfirmButton
                                label="Suspend"
                                confirmLabel="Suspend"
                                warning="Blocks this account from logging in, and ends any session it has open right now. Nothing they own is deleted."
                                pending={activeMutation.isPending}
                                onConfirm={() =>
                                  activeMutation.mutate({ userId: row.id, isActive: false })
                                }
                              />
                            ) : (
                              <button
                                onClick={() => activeMutation.mutate({ userId: row.id, isActive: true })}
                                disabled={activeMutation.isPending}
                                className="rounded border border-border px-2 py-0.5 text-2xs text-text-muted hover:bg-surface-raised hover:text-text disabled:opacity-30"
                              >
                                Restore
                              </button>
                            )}
                            <ConfirmButton
                              label="Delete account"
                              confirmLabel="Delete account"
                              warning="Deletes the account AND permanently purges every job, knowledge-base upload and conversation it owns, from disk. This cannot be undone. Suspend instead if you only want to block access."
                              pending={deleteMutation.isPending}
                              onConfirm={() => deleteMutation.mutate(row.id)}
                            />
                          </div>
                        )}
                      </div>
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

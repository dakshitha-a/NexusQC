import { useMutation, useQuery } from "@tanstack/react-query";
import * as api from "../lib/api";
import { useAuth } from "../auth/AuthContext";
import { ConfirmButton } from "./ConfirmButton";
import { UsageBar } from "./usage";

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

  const rows = usersQuery.data ?? [];
  // GET /api/admin/storage is served from a short-TTL cache, so a just-deleted
  // user can still appear in per_user for one refresh. The user list is the
  // source of truth for identity; usage is an optional lookup on top of it.
  const usageByUser = new Map(
    (storageQuery.data?.per_user ?? []).map((r) => [r.user_id, r]),
  );

  return (
    <section className="mb-5">
      <h3 className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-text-muted">
        Users
      </h3>
      <div className="overflow-x-auto rounded border border-border">
        <table className="w-full text-left text-[11px]">
          <thead className="border-b border-border text-text-muted">
            <tr>
              <th className="px-2 py-1.5 font-medium">User</th>
              <th className="px-2 py-1.5 font-medium">Role</th>
              <th className="px-2 py-1.5 font-medium">State</th>
              <th className="px-2 py-1.5 font-medium">Last login</th>
              <th className="px-2 py-1.5 font-medium">Jobs + chat</th>
              <th className="px-2 py-1.5 font-medium">Actions</th>
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
                <tr key={row.id} className="border-b border-border last:border-b-0">
                  <td className="px-2 py-1.5 text-text">
                    {row.username}
                    <span className="ml-1.5 text-text-muted">{row.email}</span>
                  </td>
                  <td className="px-2 py-1.5 text-text-muted">{row.role}</td>
                  <td className="px-2 py-1.5">
                    <span
                      className={row.is_active ? "text-status-completed" : "text-status-failed"}
                    >
                      {row.is_active ? "active" : "suspended"}
                    </span>
                  </td>
                  <td className="px-2 py-1.5 text-text-muted">
                    {row.last_login_at ? new Date(row.last_login_at).toLocaleString() : "never"}
                  </td>
                  <td className="px-2 py-1.5">
                    {usage ? (
                      <UsageBar
                        used={usage.jobs_and_chat_bytes}
                        quota={usage.jobs_and_chat_quota_bytes}
                      />
                    ) : (
                      <span className="text-text-muted">--</span>
                    )}
                  </td>
                  <td className="px-2 py-1.5">
                    {/* The backend refuses self-delete and self-deactivate
                        outright; rendering buttons that can only fail would
                        just be a worse way to learn that. */}
                    {isSelf ? (
                      <span className="text-text-muted">you</span>
                    ) : (
                      <div className="flex flex-col gap-1.5">
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
                            onClick={() =>
                              activeMutation.mutate({ userId: row.id, isActive: true })
                            }
                            disabled={activeMutation.isPending}
                            className="rounded border border-border px-2 py-0.5 text-[11px] text-text-muted hover:bg-surface-raised hover:text-text disabled:opacity-30"
                          >
                            Restore
                          </button>
                        )}
                        <ConfirmButton
                          label="Delete"
                          confirmLabel="Delete account"
                          warning="Deletes the account AND permanently purges every job, knowledge-base upload and conversation it owns, from disk. This cannot be undone. Suspend instead if you only want to block access."
                          pending={deleteMutation.isPending}
                          onConfirm={() => deleteMutation.mutate(row.id)}
                        />
                      </div>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}

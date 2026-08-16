import * as Dialog from "@radix-ui/react-dialog";
import { X, RefreshCw, AlertTriangle } from "lucide-react";
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import * as api from "../lib/api";
import type { AdminConfig } from "../lib/api";

// GB display matches StorageUsageBadge.tsx's own convention (decimal
// gigabytes, 1000^3) -- consistent with how the quota numbers this panel
// edits are described everywhere else in the app.
function formatGB(bytes: number): string {
  const gb = bytes / 1_000_000_000;
  return `${gb < 10 ? gb.toFixed(2) : gb.toFixed(1)} GB`;
}

function UsageBar({ used, quota }: { used: number; quota: number }) {
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
      <span className="text-[11px] tabular-nums text-text-muted">
        {formatGB(used)} / {formatGB(quota)}
      </span>
    </div>
  );
}

// One admin-editable quota/concurrency field: shows the current value,
// lets the admin type a new one, and PATCHes only on an explicit Save
// click -- these are rarely-changed operational settings, not something
// that needs live validation as you type. Byte-valued fields (the three
// quotas) are edited in GB, not raw bytes -- a quota like
// 19327352832 doesn't fit legibly in a compact input box, and no admin
// wants to type out a byte count by hand; `toBytes`/`fromBytes` convert
// at the component boundary so the API/backend still only ever sees bytes.
function QuotaField({
  label, description, value, unit, onSave, disabled, max,
}: {
  label: string;
  description: string;
  value: number;
  unit: "GB" | "jobs";
  onSave: (next: number) => void;
  disabled?: boolean;
  max?: number;
}) {
  const displayed = unit === "GB" ? value / 1_000_000_000 : value;
  const [draft, setDraft] = useState(String(displayed));
  const draftNum = Number(draft);
  const nextValue = unit === "GB" ? Math.round(draftNum * 1_000_000_000) : draftNum;
  const dirty = nextValue !== value && draft.trim() !== "" && !Number.isNaN(draftNum) && draftNum > 0;

  return (
    <div className="flex items-center justify-between gap-4 border-b border-border py-2.5 last:border-b-0">
      <div className="min-w-0">
        <div className="text-xs font-medium text-text">{label}</div>
        <div className="text-[11px] text-text-muted">{description}</div>
      </div>
      <div className="flex shrink-0 items-center gap-1.5">
        <input
          type="number"
          step={unit === "GB" ? 0.1 : 1}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          disabled={disabled}
          className="w-20 rounded border border-border bg-bg px-2 py-1 text-right text-xs text-text tabular-nums outline-none focus:border-accent disabled:opacity-50"
        />
        <span className="w-10 text-[11px] text-text-muted">{unit}</span>
        <button
          onClick={() => onSave(nextValue)}
          disabled={!dirty || disabled || (max !== undefined && nextValue > max)}
          className="rounded bg-accent px-2 py-1 text-[11px] font-medium text-white disabled:opacity-30"
        >
          Save
        </button>
      </div>
    </div>
  );
}

// Two-click confirm for a whole-deployment bulk purge -- mirrors
// DeleteJobButton.tsx's existing confirm pattern, scaled up with an
// explicit item count and a red warning banner since these buttons are far
// more destructive (every user's data in one category, not one job).
function PurgeButton({
  label, description, onConfirm, pending,
}: {
  label: string;
  description: string;
  onConfirm: () => void;
  pending: boolean;
}) {
  const [confirming, setConfirming] = useState(false);

  if (confirming) {
    return (
      <div className="rounded border border-status-failed/40 bg-status-failed/5 p-3">
        <div className="flex items-start gap-2 text-xs text-status-failed">
          <AlertTriangle size={14} className="mt-0.5 shrink-0" />
          <div>This deletes matching items across every user in this deployment, right now, with no undo.</div>
        </div>
        <div className="mt-2 flex justify-end gap-2">
          <button
            onClick={() => setConfirming(false)}
            className="rounded border border-border px-2.5 py-1 text-[11px] text-text-muted hover:text-text"
          >
            Cancel
          </button>
          <button
            onClick={() => {
              onConfirm();
              setConfirming(false);
            }}
            disabled={pending}
            className="rounded bg-status-failed px-2.5 py-1 text-[11px] font-medium text-white disabled:opacity-50"
          >
            {pending ? "Purging..." : "Confirm purge"}
          </button>
        </div>
      </div>
    );
  }

  return (
    <button
      onClick={() => setConfirming(true)}
      className="flex w-full items-center justify-between rounded border border-border px-3 py-2 text-left text-xs hover:border-status-failed/50 hover:bg-status-failed/5"
    >
      <span>
        <span className="font-medium text-text">{label}</span>
        <span className="ml-2 text-text-muted">{description}</span>
      </span>
    </button>
  );
}

export function AdminPanel({ onClose }: { onClose: () => void }) {
  const queryClient = useQueryClient();

  const configQuery = useQuery({ queryKey: ["admin", "config"], queryFn: api.getAdminConfig });
  // Live readout, per the deployment requirement -- refetches on an
  // interval while the panel is open rather than only on mount, and gets
  // invalidated immediately after any purge below so the numbers never
  // look stale right after an action the admin just took.
  const storageQuery = useQuery({
    queryKey: ["admin", "storage"],
    queryFn: api.getAdminStorage,
    refetchInterval: 15_000,
  });
  const auditQuery = useQuery({ queryKey: ["admin", "audit-log"], queryFn: api.getAdminAuditLog });

  const invalidateAll = () => {
    queryClient.invalidateQueries({ queryKey: ["admin"] });
  };

  const patchMutation = useMutation({
    mutationFn: ({ key, value }: { key: keyof AdminConfig; value: number | boolean }) => api.patchAdminConfig(key, value),
    onSuccess: invalidateAll,
  });
  const toggleAccessMutation = useMutation({ mutationFn: api.togglePublicAccess, onSuccess: invalidateAll });
  const purgeJobsMutation = useMutation({ mutationFn: api.purgeAllJobs, onSuccess: invalidateAll });
  const purgeKbMutation = useMutation({ mutationFn: api.purgeAllKb, onSuccess: invalidateAll });
  const purgeThreadsMutation = useMutation({ mutationFn: () => api.purgeAllThreads(false), onSuccess: invalidateAll });

  const cfg = configQuery.data;
  const storage = storageQuery.data;

  return (
    <Dialog.Root open onOpenChange={(o) => !o && onClose()}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-40 bg-black/50 data-[state=open]:animate-fade-in" />
        <Dialog.Content className="fixed left-1/2 top-1/2 z-50 flex h-[88vh] w-[94vw] max-w-4xl -translate-x-1/2 -translate-y-1/2 flex-col overflow-hidden rounded-lg border border-border bg-surface shadow-2xl data-[state=open]:animate-fade-in">
          <div className="flex items-center justify-between border-b border-border px-4 py-3">
            <Dialog.Title className="text-sm font-semibold text-text">Admin console</Dialog.Title>
            <Dialog.Close className="rounded p-1.5 text-text-muted hover:bg-surface-raised hover:text-text">
              <X size={16} />
            </Dialog.Close>
          </div>

          <div className="min-h-0 flex-1 overflow-y-auto px-4 py-4">
            {/* --- Public access ------------------------------------- */}
            <section className="mb-5">
              <div className="flex items-center justify-between rounded border border-border px-3 py-2.5">
                <div>
                  <div className="text-xs font-medium text-text">Public web access</div>
                  <div className="text-[11px] text-text-muted">
                    Soft toggle checked by the access-control middleware for the public channel -- the intranet
                    channel is never affected. For a hard kill switch that works even if this app is unresponsive,
                    use scripts/toggle_public_access.sh on the host.
                  </div>
                </div>
                <button
                  onClick={() => toggleAccessMutation.mutate()}
                  disabled={toggleAccessMutation.isPending || !cfg}
                  className={`shrink-0 rounded px-3 py-1.5 text-xs font-medium text-white disabled:opacity-50 ${
                    cfg?.public_access_enabled ? "bg-status-completed" : "bg-status-failed"
                  }`}
                >
                  {cfg?.public_access_enabled ? "Enabled -- click to disable" : "Disabled -- click to enable"}
                </button>
              </div>
            </section>

            {/* --- Quotas & concurrency -------------------------------- */}
            <section className="mb-5">
              <h3 className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-text-muted">
                Storage quotas &amp; concurrency
              </h3>
              {!cfg ? (
                <div className="text-xs text-text-muted">Loading...</div>
              ) : (
                <div className="rounded border border-border px-3">
                  <QuotaField
                    label="Per-user KB quota"
                    description="Each user's own knowledge-base uploads. Default 2GB."
                    value={cfg.per_user_kb_quota_bytes}
                    unit="GB"
                    onSave={(v) => patchMutation.mutate({ key: "per_user_kb_quota_bytes", value: v })}
                  />
                  <QuotaField
                    label="Per-user jobs + chat quota"
                    description="Each user's own job artifacts and chat history, combined into one cap. Default 18GB."
                    value={cfg.per_user_jobs_and_chat_quota_bytes}
                    unit="GB"
                    onSave={(v) => patchMutation.mutate({ key: "per_user_jobs_and_chat_quota_bytes", value: v })}
                  />
                  <QuotaField
                    label="Global storage quota"
                    description="KB + jobs + chat history combined, across every user. Default 200GB."
                    value={cfg.global_storage_quota_bytes}
                    unit="GB"
                    onSave={(v) => patchMutation.mutate({ key: "global_storage_quota_bytes", value: v })}
                  />
                  <QuotaField
                    label="Max concurrent jobs (total)"
                    description={`Cannot exceed ${cfg.max_concurrent_jobs_pool_size} -- the process's own fixed worker-pool size (QC_AGENT_MAX_CONCURRENT_JOBS).`}
                    value={cfg.max_concurrent_jobs_total}
                    unit="jobs"
                    max={cfg.max_concurrent_jobs_pool_size}
                    onSave={(v) => patchMutation.mutate({ key: "max_concurrent_jobs_total", value: v })}
                  />
                  <QuotaField
                    label="Max concurrent jobs (per user)"
                    description="How many of one user's own jobs may run at once."
                    value={cfg.max_concurrent_jobs_per_user}
                    unit="jobs"
                    onSave={(v) => patchMutation.mutate({ key: "max_concurrent_jobs_per_user", value: v })}
                  />
                </div>
              )}
            </section>

            {/* --- Live storage readout -------------------------------- */}
            <section className="mb-5">
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
                          <th className="px-2 py-1.5 font-medium">User</th>
                          <th className="px-2 py-1.5 font-medium">KB</th>
                          <th className="px-2 py-1.5 font-medium">Jobs + chat</th>
                          <th className="px-2 py-1.5 font-medium">Total</th>
                        </tr>
                      </thead>
                      <tbody>
                        {storage.per_user.length === 0 && (
                          <tr>
                            <td colSpan={4} className="px-2 py-3 text-center text-text-muted">
                              No users yet.
                            </td>
                          </tr>
                        )}
                        {storage.per_user.map((row) => (
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

            {/* --- Purge actions ----------------------------------------- */}
            <section className="mb-5">
              <h3 className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-text-muted">
                Purge history (all users)
              </h3>
              <div className="space-y-2">
                <PurgeButton
                  label="Purge all job history"
                  description="Every completed/failed/cancelled job for every user. Running jobs are never touched."
                  onConfirm={() => purgeJobsMutation.mutate()}
                  pending={purgeJobsMutation.isPending}
                />
                <PurgeButton
                  label="Purge all knowledge-base uploads"
                  description="Every user-uploaded source for every user. Pre-seeded manuals are never touched."
                  onConfirm={() => purgeKbMutation.mutate()}
                  pending={purgeKbMutation.isPending}
                />
                <PurgeButton
                  label="Purge all chat history"
                  description="Every conversation and its checkpoint storage for every user. Pinned conversations are never touched."
                  onConfirm={() => purgeThreadsMutation.mutate()}
                  pending={purgeThreadsMutation.isPending}
                />
              </div>
            </section>

            {/* --- Audit log ------------------------------------------- */}
            <section>
              <h3 className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-text-muted">
                Admin action history
              </h3>
              <div className="mb-1.5 text-[11px] text-text-muted">
                Append-only -- config changes and purges above are recorded here and cannot be edited or deleted by
                any admin, including at the database level.
              </div>
              <div className="max-h-64 overflow-y-auto rounded border border-border">
                <table className="w-full text-left text-[11px]">
                  <thead className="sticky top-0 border-b border-border bg-surface text-text-muted">
                    <tr>
                      <th className="px-2 py-1.5 font-medium">When</th>
                      <th className="px-2 py-1.5 font-medium">Action</th>
                      <th className="px-2 py-1.5 font-medium">Target</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(auditQuery.data ?? []).length === 0 && (
                      <tr>
                        <td colSpan={3} className="px-2 py-3 text-center text-text-muted">
                          No admin actions recorded yet.
                        </td>
                      </tr>
                    )}
                    {(auditQuery.data ?? []).map((row) => (
                      <tr key={row.id} className="border-b border-border last:border-b-0">
                        <td className="whitespace-nowrap px-2 py-1.5 text-text-muted">
                          {new Date(row.created_at).toLocaleString()}
                        </td>
                        <td className="px-2 py-1.5 text-text">{row.action}</td>
                        <td className="max-w-xs truncate px-2 py-1.5 text-text-muted" title={row.target ?? undefined}>
                          {row.target ?? "-"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import * as api from "../lib/api";
import type { AdminConfig } from "../lib/api";

// One admin-editable quota/concurrency field: shows the current value,
// lets the admin type a new one, and PATCHes only on an explicit Save
// click -- these are rarely-changed operational settings, not something
// that needs live validation as you type. Byte-valued fields (the three
// quotas) are edited in GB, not raw bytes -- a quota like 19327352832
// doesn't fit legibly in a compact input box, and no admin wants to type out
// a byte count by hand; the conversions happen at this component's boundary
// so the API/backend still only ever sees bytes.
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
        <div className="text-2xs text-text-muted">{description}</div>
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
        <span className="w-10 text-2xs text-text-muted">{unit}</span>
        <button
          onClick={() => onSave(nextValue)}
          disabled={!dirty || disabled || (max !== undefined && nextValue > max)}
          className="rounded bg-accent px-2 py-1 text-2xs font-medium text-on-accent disabled:opacity-30"
        >
          Save
        </button>
      </div>
    </div>
  );
}

export function OverviewSection({
  onMutationSuccess,
  onMutationError,
}: {
  onMutationSuccess: () => void;
  onMutationError: (error: unknown) => void;
}) {
  const configQuery = useQuery({ queryKey: ["admin", "config"], queryFn: api.getAdminConfig });

  const patchMutation = useMutation({
    mutationFn: ({ key, value }: { key: keyof AdminConfig; value: number | boolean }) =>
      api.patchAdminConfig(key, value),
    onSuccess: onMutationSuccess,
    onError: onMutationError,
  });

  const cfg = configQuery.data;

  return (
    <>
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
              description={`Cannot exceed ${cfg.max_concurrent_jobs_pool_size}, the process's own fixed worker-pool size (QC_AGENT_MAX_CONCURRENT_JOBS).`}
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
    </>
  );
}

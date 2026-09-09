import { useState } from "react";
import { Check, Inbox, Loader2, X } from "lucide-react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { CollapsibleSection } from "../app-shell/CollapsibleSection";
import { useLayoutStore } from "../lib/layoutStore";
import {
  jobsListQueryKey, projectsQueryKey, shareInboxQueryKey, useShareInboxQuery,
} from "../lib/queries";
import { formatBytes } from "../projects/formatBytes";
import * as api from "../lib/api";
import type { ShareRow } from "../lib/api";

/**
 * Offers other people have sent this user, in the left rail beside
 * Conversations, Knowledge base, Files and Projects.
 *
 * An offer is a database row and nothing more until it is accepted. That is
 * the whole reason this panel exists rather than shared work simply
 * appearing: accepting writes a real copy into the recipient's account and
 * spends their storage quota, so it is their decision to make. Declining
 * costs nothing, and the sender can withdraw an offer until it is answered.
 *
 * The size is shown on every row for the same reason. Accepting a 54 MB
 * orbital job is a different proposition from accepting a 24 KB single
 * point, and the quota that pays for it is the recipient's.
 *
 * The section is rendered only for a signed-in user (see LeftRail): the
 * sharing routes are mounted only when auth is configured, so on a
 * single-user local deployment there is nobody to share with and the
 * queries behind this would 404 forever.
 */
function ShareOffer({ share }: { share: ShareRow }) {
  const queryClient = useQueryClient();
  const [error, setError] = useState<string | null>(null);

  const settle = () => {
    queryClient.invalidateQueries({ queryKey: shareInboxQueryKey });
    queryClient.invalidateQueries({ queryKey: jobsListQueryKey });
    queryClient.invalidateQueries({ queryKey: projectsQueryKey });
  };

  const acceptMutation = useMutation({
    mutationFn: () => api.acceptShare(share.share_id),
    onSuccess: settle,
    // Every mutation here needs an onError. A silently failing accept is
    // exactly the shape of the bug fe_sec_02_adminpanel_silent_failure
    // exists to catch, and the most likely failure -- not enough quota --
    // is one the user can actually act on once they can read it.
    onError: (e) => setError(String(e instanceof Error ? e.message : e)),
  });

  const declineMutation = useMutation({
    mutationFn: () => api.declineShare(share.share_id),
    onSuccess: settle,
    onError: (e) => setError(String(e instanceof Error ? e.message : e)),
  });

  const pending = acceptMutation.isPending || declineMutation.isPending;
  const sender = share.from_username ?? "someone";
  const what = share.kind === "project" ? "Project" : "Job";

  return (
    <div
      data-testid={`share-offer-${share.share_id}`}
      className="flex flex-col gap-1 rounded border border-border bg-surface-raised p-2"
    >
      <div className="fade-edge-right min-w-0 text-xs text-text">{share.source_label}</div>
      <div className="flex items-center gap-1 text-3xs text-text-muted">
        <span>{what}</span>
        <span>&middot;</span>
        <span>from {sender}</span>
        <span>&middot;</span>
        <span className="tabular-nums">{formatBytes(share.size_bytes)}</span>
      </div>
      {share.note && (
        <div className="text-3xs italic text-text-muted">&ldquo;{share.note}&rdquo;</div>
      )}
      <div className="mt-0.5 flex items-center gap-1">
        <button
          onClick={() => acceptMutation.mutate()}
          disabled={pending}
          data-testid={`share-accept-${share.share_id}`}
          className="flex items-center gap-1 rounded bg-accent px-2 py-0.5 text-2xs text-on-accent disabled:opacity-40"
          title="Copy this into your own account"
        >
          {acceptMutation.isPending ? (
            <Loader2 size={10} className="animate-spin" />
          ) : (
            <Check size={10} />
          )}
          Accept
        </button>
        <button
          onClick={() => declineMutation.mutate()}
          disabled={pending}
          data-testid={`share-decline-${share.share_id}`}
          className="flex items-center gap-1 rounded border border-border px-2 py-0.5 text-2xs text-text-muted hover:text-text disabled:opacity-40"
        >
          <X size={10} />
          Decline
        </button>
      </div>
      {error && (
        <div data-testid={`share-error-${share.share_id}`} className="text-3xs text-status-failed">
          {error}
        </div>
      )}
    </div>
  );
}

export function SharedWithMeSection() {
  const { sharesCollapsed, toggleShares } = useLayoutStore();
  const inboxQuery = useShareInboxQuery();

  const rows = inboxQuery.data ?? [];
  const pendingRows = rows.filter((s) => s.status === "pending");

  return (
    <CollapsibleSection
      title="Shared with me"
      testId="shares"
      collapsed={sharesCollapsed}
      onToggle={toggleShares}
      stickyHeader
      scrollBody
      className="min-h-0"
      headerExtra={
        pendingRows.length > 0 ? (
          <span
            data-testid="share-pending-count"
            className="rounded-full bg-status-running/20 px-1.5 text-3xs font-medium tabular-nums text-status-running"
            title={`${pendingRows.length} offer${pendingRows.length === 1 ? "" : "s"} waiting for an answer`}
          >
            {pendingRows.length}
          </span>
        ) : null
      }
    >
      <div className="flex min-h-0 flex-1 flex-col gap-1.5 overflow-y-auto px-3 pb-2">
        {pendingRows.length === 0 && (
          <div data-testid="share-inbox-empty" className="flex items-center gap-1.5 py-1 text-2xs text-text-muted">
            <Inbox size={12} />
            Nothing waiting.
          </div>
        )}
        {pendingRows.map((s) => (
          <ShareOffer key={s.share_id} share={s} />
        ))}
      </div>
    </CollapsibleSection>
  );
}

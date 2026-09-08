import * as Dialog from "@radix-ui/react-dialog";
import { X, AlertTriangle, Gauge, HardDrive, Mail, ScrollText, ShieldAlert, Users, Bug, Server } from "lucide-react";
import { useState, type ReactNode } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import * as api from "../lib/api";
import { InvitesSection } from "./InvitesSection";
import { UsersSection } from "./UsersSection";
import { BugReportsSection } from "./BugReportsSection";
import { OverviewSection } from "./OverviewSection";
import { StorageSection } from "./StorageSection";
import { AuditSection } from "./AuditSection";
import { DeploymentSection } from "./DeploymentSection";
import { DangerZoneSection } from "./DangerZoneSection";

/**
 * The admin console.
 *
 * This was one 88vh dialog with nine sections stacked in a single scroller --
 * public access, five quota fields, a global storage readout, and four dense
 * 11px tables, the largest of which grows without bound. Finding anything
 * meant scrolling past everything, and each table's Actions column was the
 * last column of an `overflow-x-auto` inside a dialog narrower than the table,
 * which is how a working delete-account button came to be reported missing.
 *
 * It is now a section list plus one pane. Each section gets the whole pane, so
 * nothing competes for vertical space and the tables have room to expand rows
 * in place rather than scroll sideways.
 *
 * Section state is local `useState`, like `adminOpen` itself: there is no
 * reason for which admin tab you last looked at to survive a reload, the way
 * panel widths do.
 */
type SectionId = "overview" | "invites" | "users" | "reports" | "storage" | "audit" | "deployment" | "danger";

export function AdminPanel({ onClose }: { onClose: () => void }) {
  const queryClient = useQueryClient();
  const [section, setSection] = useState<SectionId>("overview");

  // Every mutation in this console used to have no onError/isError handling at
  // all -- a failed PATCH/purge (403, validation error, a session that expired
  // mid-click, a network blip) just silently reverted the clicked button to its
  // normal state with nothing shown to the user, confirmed via a real
  // forced-failure browser test. One shared banner (rather than a per-section
  // one) since these actions aren't run concurrently in this UI -- whichever
  // one most recently failed is what the admin needs to see, and a new attempt
  // (success or failure) always replaces or clears it.
  // tests/frontend/fe_sec_02_adminpanel_silent_failure.spec.mjs is the
  // regression test for exactly that, so every section below must be handed
  // this pair rather than keeping error state of its own.
  const [actionError, setActionError] = useState<string | null>(null);
  const onMutationError = (error: unknown) => {
    setActionError(error instanceof Error ? error.message : "Something went wrong. Please try again.");
  };
  const onMutationSuccess = () => {
    setActionError(null);
    // Invalidates the ["admin"] key PREFIX, so every section's queries refresh
    // off each other's mutations for free.
    queryClient.invalidateQueries({ queryKey: ["admin"] });
  };

  // Only for the nav badge. Cheap: this query key is already populated by the
  // reports section, so opening the console does not add a request.
  const reportsQuery = useQuery({ queryKey: ["admin", "bug-reports"], queryFn: api.listAdminBugReports });
  // Archived reports are excluded: archiving a stale one has to clear it from
  // the badge, or the count stays stuck and archiving achieves nothing
  // visible. Matches the same predicate in BugReportsSection.
  const openReports = (reportsQuery.data ?? []).filter(
    (r) => r.status === "open" && !r.archived_at,
  ).length;

  const NAV: { id: SectionId; label: string; icon: ReactNode; badge?: number; danger?: boolean }[] = [
    { id: "overview", label: "Overview", icon: <Gauge size={13} /> },
    { id: "invites", label: "Invites", icon: <Mail size={13} /> },
    { id: "users", label: "Users", icon: <Users size={13} /> },
    { id: "reports", label: "Bug reports", icon: <Bug size={13} />, badge: openReports },
    { id: "storage", label: "Storage", icon: <HardDrive size={13} /> },
    { id: "audit", label: "Audit log", icon: <ScrollText size={13} /> },
  // Between the audit log and the danger zone on purpose: reading what is
  // deployed and who is mid-calculation is ordinary operational work, but the
  // actions it will grow (restart, update) belong next to the destructive ones.
  { id: "deployment", label: "Deployment", icon: <Server size={13} /> },
    { id: "danger", label: "Danger zone", icon: <ShieldAlert size={13} />, danger: true },
  ];

  return (
    <Dialog.Root open onOpenChange={(o) => !o && onClose()}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-40 bg-black/50 data-[state=open]:animate-fade-in" />
        <Dialog.Content className="fixed left-1/2 top-1/2 z-50 flex h-[88vh] w-[94vw] max-w-5xl -translate-x-1/2 -translate-y-1/2 flex-col overflow-hidden rounded-lg border border-border bg-surface shadow-2xl data-[state=open]:animate-fade-in">
          <div className="flex shrink-0 items-center justify-between border-b border-border px-4 py-3">
            <Dialog.Title className="text-sm font-semibold text-text">Admin console</Dialog.Title>
            <Dialog.Close className="rounded p-1.5 text-text-muted hover:bg-surface-raised hover:text-text">
              <X size={16} />
            </Dialog.Close>
          </div>

          <div className="flex min-h-0 flex-1">
            <nav className="w-44 shrink-0 overflow-y-auto border-r border-border p-2">
              {NAV.map((n) => {
                const active = section === n.id;
                return (
                  <button
                    key={n.id}
                    onClick={() => setSection(n.id)}
                    data-testid={`admin-nav-${n.id}`}
                    className={`mb-0.5 flex w-full items-center gap-2 rounded px-2 py-1.5 text-left text-xs transition-colors ${
                      active
                        ? n.danger
                          ? "bg-status-failed/10 text-status-failed"
                          : "bg-surface-raised text-text"
                        : n.danger
                          ? "text-status-failed/70 hover:bg-status-failed/5 hover:text-status-failed"
                          : "text-text-muted hover:bg-surface-raised hover:text-text"
                    }`}
                  >
                    {n.icon}
                    <span className="min-w-0 flex-1 truncate">{n.label}</span>
                    {n.badge ? (
                      <span className="shrink-0 rounded-full bg-status-running/20 px-1.5 text-[10px] font-medium text-status-running">
                        {n.badge}
                      </span>
                    ) : null}
                  </button>
                );
              })}
            </nav>

            <div className="min-h-0 min-w-0 flex-1 overflow-y-auto px-4 py-4">
              {actionError && (
                <div className="mb-4 flex items-start gap-2 rounded border border-status-failed/40 bg-status-failed/5 px-3 py-2 text-xs text-status-failed">
                  <AlertTriangle size={14} className="mt-0.5 shrink-0" />
                  <div className="min-w-0 flex-1 break-words">{actionError}</div>
                  <button
                    onClick={() => setActionError(null)}
                    className="shrink-0 text-status-failed/70 hover:text-status-failed"
                  >
                    <X size={12} />
                  </button>
                </div>
              )}

              {section === "overview" && (
                <OverviewSection onMutationSuccess={onMutationSuccess} onMutationError={onMutationError} />
              )}
              {section === "invites" && (
                <InvitesSection onMutationSuccess={onMutationSuccess} onMutationError={onMutationError} />
              )}
              {section === "users" && (
                <UsersSection onMutationSuccess={onMutationSuccess} onMutationError={onMutationError} />
              )}
              {section === "reports" && (
                <BugReportsSection onMutationSuccess={onMutationSuccess} onMutationError={onMutationError} />
              )}
              {section === "storage" && <StorageSection />}
              {section === "audit" && <AuditSection />}
              {section === "deployment" && <DeploymentSection />}
              {section === "danger" && (
                <DangerZoneSection onMutationSuccess={onMutationSuccess} onMutationError={onMutationError} />
              )}
            </div>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

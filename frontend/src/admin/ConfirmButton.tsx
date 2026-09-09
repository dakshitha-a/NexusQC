import { AlertTriangle } from "lucide-react";
import { useState } from "react";

/**
 * A compact two-click confirm sized for a table cell.
 *
 * This is the same mechanic as AdminPanel.tsx's PurgeButton, deliberately
 * duplicated rather than shared: PurgeButton is a full-width block whose
 * warning copy is hardcoded to "across every user in this deployment",
 * which is both the wrong shape and the wrong sentence inside a per-row
 * Actions column. What matters is that the *pattern* is the same -- no
 * destructive admin action in this app is ever one click, and none of them
 * use a native confirm() dialog.
 *
 * The literal strings "Cancel" and "Confirm" are load-bearing:
 * tests/e2e/ui/ui_04_admin_visual.spec.mjs locates confirm panels by button
 * text.
 */
export function ConfirmButton({
  label,
  confirmLabel,
  warning,
  onConfirm,
  pending,
  disabled,
}: {
  label: string;
  confirmLabel: string;
  warning: string;
  onConfirm: () => void;
  pending: boolean;
  disabled?: boolean;
}) {
  const [confirming, setConfirming] = useState(false);

  if (confirming) {
    return (
      <div className="rounded border border-status-failed/40 bg-status-failed/5 p-2">
        <div className="flex items-start gap-1.5 text-2xs text-status-failed">
          <AlertTriangle size={12} className="mt-0.5 shrink-0" />
          <div className="min-w-0 break-words">{warning}</div>
        </div>
        <div className="mt-1.5 flex justify-end gap-1.5">
          <button
            onClick={() => setConfirming(false)}
            className="rounded border border-border px-2 py-0.5 text-2xs text-text-muted hover:text-text"
          >
            Cancel
          </button>
          <button
            onClick={() => {
              onConfirm();
              setConfirming(false);
            }}
            disabled={pending}
            className="rounded bg-status-failed px-2 py-0.5 text-2xs font-medium text-on-status-failed disabled:opacity-50"
          >
            {pending ? "Working..." : confirmLabel}
          </button>
        </div>
      </div>
    );
  }

  return (
    <button
      onClick={() => setConfirming(true)}
      disabled={disabled}
      className="rounded border border-border px-2 py-0.5 text-2xs text-text-muted hover:border-status-failed/50 hover:bg-status-failed/5 hover:text-status-failed disabled:opacity-30 disabled:hover:border-border disabled:hover:bg-transparent disabled:hover:text-text-muted"
    >
      {label}
    </button>
  );
}

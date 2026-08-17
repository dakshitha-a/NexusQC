import { useState } from "react";
import { Download, Loader2 } from "lucide-react";

/**
 * One download control, for the roughly ten of them these features add.
 *
 * `onDownload` may be sync or async. While an async one is in flight the button
 * shows a spinner and refuses further clicks -- which matters for the APNG
 * capture, where the work takes about four seconds and the viewer visibly turns
 * white while it happens.
 *
 * Errors are reported through `onError` rather than thrown or swallowed: the
 * job drawer already has a `downloadError` banner, and a capture that fails
 * silently looks exactly like a button that does nothing.
 */
export function DownloadButton({
  onDownload,
  title,
  testId,
  size = 15,
  className = "",
  disabled = false,
  onError,
}: {
  onDownload: () => void | Promise<void>;
  // Distinct per control, always. There were once three colliding
  // [title="Download as PNG"] buttons, which made every one of them
  // ambiguous to a test and to a screen reader alike.
  title: string;
  testId: string;
  size?: number;
  className?: string;
  disabled?: boolean;
  onError?: (message: string) => void;
}) {
  const [busy, setBusy] = useState(false);
  return (
    <button
      type="button"
      title={title}
      aria-label={title}
      data-testid={testId}
      disabled={disabled || busy}
      onClick={async () => {
        if (busy) return;
        setBusy(true);
        try {
          await onDownload();
        } catch (e) {
          onError?.(String(e instanceof Error ? e.message : e));
        } finally {
          setBusy(false);
        }
      }}
      className={`rounded p-1.5 text-text-muted hover:bg-surface-raised hover:text-text disabled:cursor-not-allowed disabled:opacity-50 ${className}`}
    >
      {busy ? <Loader2 size={size} className="animate-spin" /> : <Download size={size} />}
    </button>
  );
}

import { useState } from "react";
import { ImagePlus, X } from "lucide-react";
import { Flyout } from "../app-shell/Flyout";
import { useAuth } from "../auth/AuthContext";
import * as api from "../lib/api";
import { ApiError } from "../lib/api";

const INPUT_CLASS =
  "rounded-md border border-border bg-surface-raised px-3 py-2 text-sm text-text placeholder:text-text-muted focus:border-accent focus:outline-none";

const MAX_SHOTS = 3;
const MAX_SHOT_BYTES = 5 * 1024 * 1024;

/**
 * Report a bug, with screenshots.
 *
 * The paste handler is the important half. A screenshot taken with the OS
 * shortcut lands on the clipboard, and asking someone to save it to disk first
 * just so they can pick it from a file dialog is how a screenshot ends up not
 * being attached at all. Ctrl-V into the textarea attaches it directly; the
 * file picker stays for images that really are already files.
 *
 * The size and count limits are duplicated from server/routes/bugs.py on
 * purpose -- the server's copy is the one that counts (a client-only limit is
 * bypassed by calling the API directly), and this one exists so the failure is
 * immediate and specific instead of a 422 after an upload.
 */
function BugReportForm() {
  const [body, setBody] = useState("");
  const [shots, setShots] = useState<File[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  const addFiles = (incoming: File[]) => {
    setDone(false);
    const images = incoming.filter((f) => f.type.startsWith("image/"));
    if (images.length !== incoming.length) {
      setError("Only images can be attached.");
      return;
    }
    const tooBig = images.find((f) => f.size > MAX_SHOT_BYTES);
    if (tooBig) {
      setError(`"${tooBig.name}" is over ${MAX_SHOT_BYTES / (1024 * 1024)}MB.`);
      return;
    }
    setShots((prev) => {
      if (prev.length + images.length > MAX_SHOTS) {
        setError(`At most ${MAX_SHOTS} screenshots per report.`);
        return prev;
      }
      setError(null);
      return [...prev, ...images];
    });
  };

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setDone(false);
    setSubmitting(true);
    try {
      await api.submitBugReport(body, shots);
      setBody("");
      setShots([]);
      setDone(true);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong. Please try again.");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <form onSubmit={submit} className="flex flex-col gap-2">
      <textarea
        value={body}
        onChange={(e) => setBody(e.target.value)}
        onPaste={(e) => {
          const pasted = Array.from(e.clipboardData.files);
          if (pasted.length) {
            // Only intercept when the clipboard actually carries files --
            // otherwise this would swallow ordinary text pastes.
            e.preventDefault();
            addFiles(pasted);
          }
        }}
        rows={6}
        required
        autoFocus
        data-testid="bug-report-body"
        placeholder="What went wrong? Include the job id or conversation if there is one. You can paste a screenshot straight in."
        className={INPUT_CLASS}
      />

      <div className="flex items-center gap-2">
        <label className="cursor-pointer rounded-md border border-border px-2 py-1 text-xs text-text-muted hover:bg-surface-raised hover:text-text">
          <ImagePlus size={12} className="mr-1 inline" />
          Attach screenshot
          <input
            type="file"
            accept="image/*"
            multiple
            data-testid="bug-report-files"
            className="hidden"
            onChange={(e) => {
              addFiles(Array.from(e.target.files ?? []));
              // Reset, so picking the same file twice in a row still fires.
              e.target.value = "";
            }}
          />
        </label>
        <span className="text-[11px] text-text-muted">
          or paste one into the box above · up to {MAX_SHOTS}
        </span>
      </div>

      {shots.length > 0 && (
        <div className="flex flex-wrap gap-2" data-testid="bug-report-thumbs">
          {shots.map((f, i) => (
            <div key={`${f.name}-${i}`} className="relative">
              <img
                src={URL.createObjectURL(f)}
                alt={f.name}
                className="size-16 rounded border border-border object-cover"
              />
              <button
                type="button"
                onClick={() => setShots((prev) => prev.filter((_, j) => j !== i))}
                title={`Remove ${f.name}`}
                className="absolute -right-1.5 -top-1.5 rounded-full border border-border bg-surface p-0.5 text-text-muted hover:text-status-failed"
              >
                <X size={10} />
              </button>
            </div>
          ))}
        </div>
      )}

      {error && <div className="text-xs text-status-failed">{error}</div>}
      {done && <div className="text-xs text-status-completed">Thanks -- your report was sent.</div>}
      <button
        type="submit"
        disabled={submitting || body.trim().length === 0}
        data-testid="bug-report-submit"
        className="self-start rounded-md border border-border px-3 py-1.5 text-xs text-text-muted hover:bg-surface-raised hover:text-text disabled:opacity-50"
      >
        {submitting ? "Sending..." : "Send report"}
      </button>
    </form>
  );
}

/**
 * Filing a bug gets its own entry in the account menu rather than living
 * inside the account panel.
 *
 * It was never role-gated -- every signed-in user, admin included, has always
 * been able to file one. It was simply unreachable in practice for an admin:
 * the cogwheel offers an admin console, the console's Bug reports section is
 * the *inbox*, and nothing there hints that the way to file one is to back out
 * into Account settings and scroll past the change-password form. Reported as
 * "admins should also have a bug report button", which is a discoverability
 * bug rather than a missing capability -- the same shape as the delete-account
 * button that was scrolled off the side of a table.
 *
 * Deliberately moved rather than duplicated. Two entry points to one form
 * raises the question of whether they are the same form, and this one now has
 * a single home named after what it does.
 */
export function BugReportFlyout({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { user } = useAuth();
  if (!user) return null;

  return (
    <Flyout open={open} onClose={onClose} title="Report a bug" widthClassName="w-105">
      <p className="mb-3 text-xs text-text-muted">
        Goes straight to whoever administers this deployment, along with your username and the time.
        Screenshots help more than anything else you can write.
      </p>
      <BugReportForm />
    </Flyout>
  );
}

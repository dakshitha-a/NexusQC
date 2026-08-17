import { useState } from "react";
import { Flyout } from "../app-shell/Flyout";
import { useAuth } from "../auth/AuthContext";
import * as api from "../lib/api";
import { ApiError } from "../lib/api";

const INPUT_CLASS =
  "rounded-md border border-border bg-surface-raised px-3 py-2 text-sm text-text placeholder:text-text-muted focus:border-accent focus:outline-none";

function ChangePasswordForm() {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  const mismatch = confirm.length > 0 && next !== confirm;
  const canSubmit =
    current.length > 0 && next.length >= 8 && next === confirm && !submitting;

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setDone(false);
    setSubmitting(true);
    try {
      await api.changePassword(current, next);
      setCurrent("");
      setNext("");
      setConfirm("");
      setDone(true);
    } catch (err) {
      // A wrong current password comes back 400, not 401 -- see the comment
      // in server/routes/auth.py's change_password. A 401 here would trip
      // lib/api.ts's global auth-error handler and bounce the user to the
      // login screen over a typo.
      setError(err instanceof ApiError ? err.message : "Something went wrong. Please try again.");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <form onSubmit={submit} className="flex flex-col gap-3">
      <input
        type="password"
        autoComplete="current-password"
        placeholder="Current password"
        value={current}
        onChange={(e) => setCurrent(e.target.value)}
        required
        className={INPUT_CLASS}
      />
      <input
        type="password"
        autoComplete="new-password"
        placeholder="New password (at least 8 characters)"
        value={next}
        onChange={(e) => setNext(e.target.value)}
        required
        minLength={8}
        className={INPUT_CLASS}
      />
      <input
        type="password"
        autoComplete="new-password"
        placeholder="Confirm new password"
        value={confirm}
        onChange={(e) => setConfirm(e.target.value)}
        required
        className={INPUT_CLASS}
      />

      {mismatch && <div className="text-xs text-status-failed">The new passwords don't match.</div>}
      {error && (
        <div data-testid="change-password-error" className="text-xs text-status-failed">
          {error}
        </div>
      )}
      {done && (
        <div data-testid="change-password-done" className="text-xs text-status-completed">
          Password changed. You're still signed in here, but every other device has been signed
          out.
        </div>
      )}

      <button
        type="submit"
        disabled={!canSubmit}
        data-testid="change-password-submit"
        className="mt-1 rounded-md bg-accent px-3 py-2 text-sm font-medium text-bg disabled:opacity-50"
      >
        {submitting ? "Please wait..." : "Change password"}
      </button>
      {/* Real, observable behaviour worth stating up front rather than
          letting someone discover it and file it as a bug: change_password
          calls the same _start_session a fresh login does, which overwrites
          the Redis active-session key and kills every other cookie for this
          user. */}
      <p className="text-xs text-text-muted">
        Changing your password signs out this account everywhere else.
      </p>
    </form>
  );
}

function BugReportForm() {
  const [body, setBody] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setDone(false);
    setSubmitting(true);
    try {
      await api.submitBugReport(body);
      setBody("");
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
        rows={4}
        required
        placeholder="What went wrong? Include the job id or conversation if there is one."
        className={INPUT_CLASS}
      />
      {error && <div className="text-xs text-status-failed">{error}</div>}
      {done && <div className="text-xs text-status-completed">Thanks -- your report was sent.</div>}
      <button
        type="submit"
        disabled={submitting || body.trim().length === 0}
        className="self-start rounded-md border border-border px-3 py-1.5 text-xs text-text-muted hover:bg-surface-raised hover:text-text disabled:opacity-50"
      >
        {submitting ? "Sending..." : "Send report"}
      </button>
    </form>
  );
}

/**
 * The account panel every signed-in user gets, admin or not.
 *
 * Uses Flyout rather than AdminPanel's centred dialog: this is the app's
 * existing slide-in convention (HelpFlyout is the other consumer), and an
 * 88vh modal would be absurd for one three-field form.
 *
 * Its caller in ShellLayout renders it inside AccountBar's `if (!user)
 * return null` guard, which is what keeps it off no-auth local-dev
 * deployments -- there the auth router is never mounted at all, so
 * /api/auth/change-password would simply 404.
 */
export function AccountFlyout({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { user } = useAuth();
  if (!user) return null;

  return (
    <Flyout open={open} onClose={onClose} title="Account" widthClassName="w-96">
      <div className="mb-5 rounded border border-border px-3 py-2">
        <div className="text-sm text-text">{user.username}</div>
        <div className="text-xs text-text-muted">{user.email}</div>
        <div className="mt-1 text-xs text-text-muted">Role: {user.role}</div>
      </div>

      <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-text-muted">
        Change password
      </h3>
      <ChangePasswordForm />

      <h3 className="mb-2 mt-6 text-xs font-semibold uppercase tracking-wide text-text-muted">
        Report a bug
      </h3>
      <BugReportForm />
    </Flyout>
  );
}

import { useState } from "react";
import { ApiError, login, register, resetPassword } from "../lib/api";

type Mode = "login" | "register" | "reset";

const FIELD =
  "rounded-md border border-border bg-surface-raised px-3 py-2 text-sm text-text placeholder:text-text-muted focus:border-accent focus:outline-none";

// The whole deep-link contract for this screen: a bare ?invite= flips it into
// register mode, a bare ?reset= into reset mode. There is no router in this
// app, so these two query params are it. InvitesSection.inviteLink() and
// UsersSection.resetLink() are the other halves.
function initialMode(): Mode {
  const params = new URLSearchParams(window.location.search);
  if (params.has("reset")) return "reset";
  if (params.has("invite")) return "register";
  return "login";
}

// Frosted-glass card against a dark background, per the deployment
// design ask -- this app's dark theme (index.css's --bg/--surface tokens)
// already does most of that work; the backdrop-blur + translucent surface
// on the card itself is the one new visual element this screen needs.
export function LoginScreen({ onAuthenticated }: { onAuthenticated: () => void }) {
  const [mode, setMode] = useState<Mode>(initialMode);
  const [emailOrUsername, setEmailOrUsername] = useState("");
  const [email, setEmail] = useState("");
  const [username, setUsername] = useState("");
  const [firstName, setFirstName] = useState("");
  const [lastName, setLastName] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [inviteToken, setInviteToken] = useState(
    () => new URLSearchParams(window.location.search).get("invite") ?? "",
  );
  const [resetToken, setResetToken] = useState(
    () => new URLSearchParams(window.location.search).get("reset") ?? "",
  );
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  function switchTo(next: Mode) {
    setError(null);
    setMode(next);
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    // Checked here rather than left to the server: the confirm field exists
    // only in the browser, and a mistyped new password on an account you
    // cannot already get into is expensive to discover later -- the token is
    // single-use, so it would be spent on a password nobody knows.
    if (mode === "reset" && password !== confirmPassword) {
      setError("The two passwords do not match.");
      return;
    }
    setSubmitting(true);
    try {
      if (mode === "login") {
        await login(emailOrUsername, password);
      } else if (mode === "register") {
        await register(inviteToken, email, username, password, firstName, lastName);
      } else {
        await resetPassword(resetToken, password);
      }
      onAuthenticated();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong. Please try again.");
    } finally {
      setSubmitting(false);
    }
  }

  const blurb =
    mode === "login"
      ? "Sign in to continue."
      : mode === "register"
        ? "Create an account with your invite token."
        : "Set a new password using the reset token an administrator gave you.";

  const submitLabel =
    mode === "login" ? "Sign in" : mode === "register" ? "Create account" : "Set new password";

  return (
    <div className="flex h-full w-full items-center justify-center bg-bg p-4">
      <div className="w-full max-w-sm rounded-xl border border-border bg-surface/70 p-8 shadow-2xl backdrop-blur-md">
        <h1 className="text-lg font-semibold leading-tight text-text">NexusQC</h1>
        <p className="mb-5 text-xs text-text-muted">Agentic Quantum Chemistry Engine</p>
        <p className="mb-6 text-sm text-text-muted" data-testid="auth-blurb">{blurb}</p>

        <form onSubmit={handleSubmit} className="flex flex-col gap-3" data-testid={`auth-form-${mode}`}>
          {mode === "register" && (
            <input
              type="text"
              placeholder="Invite token"
              value={inviteToken}
              onChange={(e) => setInviteToken(e.target.value)}
              required
              className={FIELD}
            />
          )}
          {mode === "reset" && (
            <input
              type="text"
              placeholder="Reset token"
              value={resetToken}
              onChange={(e) => setResetToken(e.target.value)}
              required
              data-testid="reset-token"
              className={FIELD}
            />
          )}
          {mode === "register" && (
            <input
              type="email"
              placeholder="Email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
              className={FIELD}
            />
          )}
          {mode === "register" && (
            <div className="flex gap-3">
              <input
                type="text"
                placeholder="First name"
                value={firstName}
                onChange={(e) => setFirstName(e.target.value)}
                required
                className={`w-1/2 ${FIELD}`}
              />
              <input
                type="text"
                placeholder="Last name"
                value={lastName}
                onChange={(e) => setLastName(e.target.value)}
                required
                className={`w-1/2 ${FIELD}`}
              />
            </div>
          )}
          {mode !== "reset" && (
            <input
              type="text"
              placeholder={mode === "login" ? "Username or email" : "Username"}
              value={mode === "login" ? emailOrUsername : username}
              onChange={(e) =>
                mode === "login" ? setEmailOrUsername(e.target.value) : setUsername(e.target.value)
              }
              required
              className={FIELD}
            />
          )}
          <input
            type="password"
            placeholder={mode === "reset" ? "New password" : "Password"}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
            minLength={mode === "login" ? undefined : 8}
            data-testid={mode === "reset" ? "reset-password" : undefined}
            className={FIELD}
          />
          {mode === "reset" && (
            <input
              type="password"
              placeholder="Confirm new password"
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
              required
              minLength={8}
              data-testid="reset-confirm"
              className={FIELD}
            />
          )}

          {error && <div className="text-xs text-status-failed" data-testid="auth-error">{error}</div>}

          <button
            type="submit"
            disabled={submitting}
            data-testid="auth-submit"
            className="mt-2 rounded-md bg-accent px-3 py-2 text-sm font-medium text-bg disabled:opacity-50"
          >
            {submitting ? "Please wait..." : submitLabel}
          </button>
        </form>

        {mode === "reset" && (
          // Said plainly because there is no mail server in this deployment:
          // there is no link to send yourself, and a "check your email" line
          // would be a dead end. An admin issues the token by hand.
          <p className="mt-4 text-xs text-text-muted">
            Reset tokens are issued by an administrator and can be used once. Ask one for a
            reset link if you do not have a token.
          </p>
        )}

        <div className="mt-4 flex flex-col gap-2">
          {mode === "login" && (
            <button
              type="button"
              onClick={() => switchTo("reset")}
              data-testid="forgot-password"
              className="self-start text-xs text-text-muted underline decoration-dotted hover:text-text"
            >
              Forgot your password?
            </button>
          )}
          <button
            type="button"
            onClick={() => switchTo(mode === "login" ? "register" : "login")}
            className="self-start text-xs text-text-muted underline decoration-dotted hover:text-text"
          >
            {mode === "login"
              ? "Have an invite token? Create an account"
              : "Already have an account? Sign in"}
          </button>
        </div>
      </div>
    </div>
  );
}

import { useState } from "react";
import { ApiError, login, register } from "../lib/api";

// Frosted-glass card against a dark background, per the deployment
// design ask -- this app's dark theme (index.css's --bg/--surface tokens)
// already does most of that work; the backdrop-blur + translucent surface
// on the card itself is the one new visual element this screen needs.
export function LoginScreen({ onAuthenticated }: { onAuthenticated: () => void }) {
  const [mode, setMode] = useState<"login" | "register">(() =>
    new URLSearchParams(window.location.search).has("invite") ? "register" : "login",
  );
  const [emailOrUsername, setEmailOrUsername] = useState("");
  const [email, setEmail] = useState("");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [inviteToken, setInviteToken] = useState(
    () => new URLSearchParams(window.location.search).get("invite") ?? "",
  );
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      if (mode === "login") {
        await login(emailOrUsername, password);
      } else {
        await register(inviteToken, email, username, password);
      }
      onAuthenticated();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong. Please try again.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="flex h-full w-full items-center justify-center bg-bg p-4">
      <div className="w-full max-w-sm rounded-xl border border-border bg-surface/70 p-8 shadow-2xl backdrop-blur-md">
        <h1 className="text-lg font-semibold leading-tight text-text">NexusQC</h1>
        <p className="mb-5 text-xs text-text-muted">Agentic Quantum Chemistry Engine</p>
        <p className="mb-6 text-sm text-text-muted">
          {mode === "login" ? "Sign in to continue." : "Create an account with your invite token."}
        </p>

        <form onSubmit={handleSubmit} className="flex flex-col gap-3">
          {mode === "register" && (
            <input
              type="text"
              placeholder="Invite token"
              value={inviteToken}
              onChange={(e) => setInviteToken(e.target.value)}
              required
              className="rounded-md border border-border bg-surface-raised px-3 py-2 text-sm text-text placeholder:text-text-muted focus:border-accent focus:outline-none"
            />
          )}
          {mode === "register" && (
            <input
              type="email"
              placeholder="Email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
              className="rounded-md border border-border bg-surface-raised px-3 py-2 text-sm text-text placeholder:text-text-muted focus:border-accent focus:outline-none"
            />
          )}
          <input
            type="text"
            placeholder={mode === "login" ? "Username or email" : "Username"}
            value={mode === "login" ? emailOrUsername : username}
            onChange={(e) => (mode === "login" ? setEmailOrUsername(e.target.value) : setUsername(e.target.value))}
            required
            className="rounded-md border border-border bg-surface-raised px-3 py-2 text-sm text-text placeholder:text-text-muted focus:border-accent focus:outline-none"
          />
          <input
            type="password"
            placeholder="Password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
            minLength={mode === "register" ? 8 : undefined}
            className="rounded-md border border-border bg-surface-raised px-3 py-2 text-sm text-text placeholder:text-text-muted focus:border-accent focus:outline-none"
          />

          {error && <div className="text-xs text-status-failed">{error}</div>}

          <button
            type="submit"
            disabled={submitting}
            className="mt-2 rounded-md bg-accent px-3 py-2 text-sm font-medium text-bg disabled:opacity-50"
          >
            {submitting ? "Please wait..." : mode === "login" ? "Sign in" : "Create account"}
          </button>
        </form>

        <button
          type="button"
          onClick={() => {
            setError(null);
            setMode(mode === "login" ? "register" : "login");
          }}
          className="mt-4 text-xs text-text-muted underline decoration-dotted hover:text-text"
        >
          {mode === "login" ? "Have an invite token? Create an account" : "Already have an account? Sign in"}
        </button>
      </div>
    </div>
  );
}

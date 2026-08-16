import { createContext, useContext } from "react";
import type { CurrentUser } from "../lib/api";

// Populated only once AuthGate has confirmed a real logged-in user -- null
// means "auth isn't configured for this deployment" (local dev without
// Postgres, see AuthGate.tsx), never "loading" or "logged out" (AuthGate
// doesn't render its children at all in those states).
export const AuthContext = createContext<{ user: CurrentUser | null; logout: () => void } | null>(null);

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (ctx === null) {
    throw new Error("useAuth() called outside AuthGate -- every component under ShellLayout is mounted inside it, so this indicates a real bug, not a config difference");
  }
  return ctx;
}

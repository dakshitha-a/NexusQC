import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError, getMe, logout as apiLogout } from "../lib/api";
import { AuthContext } from "./AuthContext";
import { LoginScreen } from "./LoginScreen";

// Zero-trust gate: renders nothing but a login screen until a real session
// is confirmed. Deliberately no router (this app has none -- see
// frontend/package.json, no react-router dependency) -- a binary
// authed/not-authed state plus one admin-panel mode toggle later doesn't
// justify introducing one; this is the same plain conditional-render
// pattern every other panel in this app already uses (see layoutStore).
//
// A 404 on GET /api/auth/me (rather than 401) means auth isn't wired into
// this backend at all -- the local-dev workflow (no QC_AGENT_DATABASE_URL,
// server/main.py never mounts server/routes/auth.py) -- so the gate steps
// aside entirely rather than showing a login screen with nowhere to log
// into. This is what keeps `python -m server.main` + `npm run dev` working
// unchanged for anyone not running the containerized multi-user stack.
export function AuthGate({ children }: { children: React.ReactNode }) {
  const queryClient = useQueryClient();
  const { data, error, isLoading } = useQuery({
    queryKey: ["auth", "me"],
    queryFn: getMe,
    retry: false,
    staleTime: 60_000,
  });

  if (isLoading) {
    return (
      <div className="flex h-full w-full items-center justify-center bg-bg text-text-muted">
        <div className="text-sm">Loading...</div>
      </div>
    );
  }

  if (error instanceof ApiError && error.status === 404) {
    // Auth not configured for this deployment -- render the app directly,
    // with a context value of `user: null` so any component that reads
    // useAuth() (e.g. a future "log out" button) degrades to not rendering
    // itself rather than crashing.
    return <AuthContext.Provider value={{ user: null, logout: () => {} }}>{children}</AuthContext.Provider>;
  }

  if (error instanceof ApiError && error.status === 401) {
    return (
      <LoginScreen
        onAuthenticated={() => {
          queryClient.invalidateQueries({ queryKey: ["auth", "me"] });
        }}
      />
    );
  }

  if (error) {
    return (
      <div className="flex h-full w-full items-center justify-center bg-bg text-status-failed">
        <div className="text-sm">Could not reach the server. Retry by reloading the page.</div>
      </div>
    );
  }

  const logout = () => {
    apiLogout().finally(() => {
      queryClient.invalidateQueries({ queryKey: ["auth", "me"] });
    });
  };

  return <AuthContext.Provider value={{ user: data ?? null, logout }}>{children}</AuthContext.Provider>;
}

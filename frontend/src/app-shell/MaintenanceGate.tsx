import { useEffect, useState } from "react";
import { registerMaintenanceHandler } from "../lib/api";
import { useAuth } from "../auth/AuthContext";
import { MaintenanceOverlay } from "./MaintenanceOverlay";

/**
 * Turns the api client's maintenance signal into something on screen.
 *
 * Sits INSIDE AuthGate so it can ask who is looking -- an admin driving the
 * update needs to be able to put the overlay aside and keep using the panel,
 * and everybody else does not. It listens rather than polls: every query in
 * the app already polls, so the first one to get a 503 during an update is
 * what wakes this up. Building an app-level event stream to announce a
 * restart would be new plumbing for a signal that already arrives.
 *
 * The deploy id is read from sessionStorage, written by the admin panel when
 * it submits an update. A tab that did not start the update has no id and
 * falls back to watching /api/health, which is the right answer for the case
 * where somebody updated from a shell and no request file exists at all.
 */
export const DEPLOY_ID_KEY = "nexusqc.deploy.id";

export function MaintenanceGate({ children }: { children: React.ReactNode }) {
  const { user } = useAuth();
  const [message, setMessage] = useState<string | null>(null);
  const [dismissed, setDismissed] = useState(false);

  useEffect(() => {
    registerMaintenanceHandler((m) => {
      setMessage(m);
      setDismissed(false);
    });
  }, []);

  let deployId: string | null = null;
  try {
    deployId = window.sessionStorage.getItem(DEPLOY_ID_KEY);
  } catch {
    /* private mode, or storage blocked. Health-polling still works. */
  }

  return (
    <>
      {children}
      {message && !dismissed && (
        <MaintenanceOverlay
          message={message}
          deployId={deployId}
          isAdmin={user?.role === "admin"}
          onDismiss={() => setDismissed(true)}
        />
      )}
    </>
  );
}

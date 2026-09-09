import { Download } from "lucide-react";
import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { PurgeAction } from "../admin/DangerZoneSection";
import { Flyout } from "../app-shell/Flyout";
import { useAuth } from "../auth/AuthContext";
import * as api from "../lib/api";
import { ApiError } from "../lib/api";
import { jobsListQueryKey, projectsQueryKey } from "../lib/queries";

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
        className="mt-1 rounded-md bg-accent px-3 py-2 text-sm font-medium text-on-accent disabled:opacity-50"
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

/**
 * P9.4's self-scoped danger zone: a signed-in user deleting their OWN
 * jobs, KB uploads and geometry/blind-input uploads (never chat threads --
 * see purge_own_data's own docstring in app/auth/storage_quota.py for why
 * that is a deliberately narrower scope than admin-driven account
 * deletion), plus a "download all my data" zip covering the same three
 * categories. Reuses PurgeAction (DangerZoneSection.tsx) rather than a
 * second typed-confirmation implementation: "delete everything I own" has
 * the same no-undo weight as the admin console's deployment-wide purges,
 * just scoped to one person instead of everyone.
 */
function SelfDangerZone() {
  const [result, setResult] = useState<{ jobs: number; kb: number; uploads: number } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [projectResult, setProjectResult] = useState<{ projects: number; jobs: number } | null>(null);
  const [projectError, setProjectError] = useState<string | null>(null);
  const queryClient = useQueryClient();

  // Scoped server-side to the projects this user OWNS, never to whatever
  // GET /api/projects happens to show -- an admin sees every project on
  // the deployment there, and "delete all of MY projects" must not mean
  // everyone's. See server/routes/projects.py's purge_my_projects.
  const purgeProjects = useMutation({
    mutationFn: api.purgeMyProjects,
    onSuccess: (r) => {
      setProjectError(null);
      setProjectResult({ projects: r.purged_projects, jobs: r.purged_jobs });
      queryClient.invalidateQueries({ queryKey: projectsQueryKey });
      queryClient.invalidateQueries({ queryKey: jobsListQueryKey });
    },
    onError: (err) => {
      setProjectResult(null);
      setProjectError(err instanceof ApiError ? err.message : "Something went wrong. Please try again.");
    },
  });
  const purge = useMutation({
    mutationFn: api.purgeMyData,
    onSuccess: (r) => {
      setError(null);
      setResult({ jobs: r.purged_jobs, kb: r.purged_kb_sources, uploads: r.purged_uploads });
    },
    onError: (err) => {
      setResult(null);
      setError(err instanceof ApiError ? err.message : "Something went wrong. Please try again.");
    },
  });

  return (
    <div className="space-y-3">
      <a
        href={api.downloadMyDataUrl()}
        download
        data-testid="download-my-data"
        className="flex items-center gap-2 rounded-md border border-border px-3 py-2 text-sm text-text hover:bg-surface-raised"
      >
        <Download size={14} />
        Download all my data
      </a>
      <p className="text-xs text-text-muted">
        A zip of every job, knowledge-base upload and geometry/input file upload you own.
      </p>

      <PurgeAction
        label="Delete all my data"
        description="Every job you own (a still-running one is stopped first), every knowledge-base source you've added, and every geometry/input file you've uploaded. Your conversations and your account itself are not affected. There is no undo."
        phrase="DELETE MY DATA"
        testId="self-purge"
        onConfirm={() => purge.mutate()}
        pending={purge.isPending}
      />
      {error && (
        <div data-testid="self-purge-error" className="text-xs text-status-failed">
          {error}
        </div>
      )}
      {result && (
        <div data-testid="self-purge-done" className="text-xs text-status-completed">
          Deleted {result.jobs} job{result.jobs === 1 ? "" : "s"}, {result.kb} knowledge-base source
          {result.kb === 1 ? "" : "s"}, and {result.uploads} upload{result.uploads === 1 ? "" : "s"}.
        </div>
      )}

      <PurgeAction
        label="Delete all my projects"
        description="Every project archive you own, and every job filed into one. Jobs that are not in a project are not affected, and neither are your conversations or your account. Anything still running is stopped first. There is no undo."
        phrase="DELETE MY PROJECTS"
        testId="self-purge-projects"
        onConfirm={() => purgeProjects.mutate()}
        pending={purgeProjects.isPending}
      />
      {projectError && (
        <div data-testid="self-purge-projects-error" className="text-xs text-status-failed">
          {projectError}
        </div>
      )}
      {projectResult && (
        <div data-testid="self-purge-projects-done" className="text-xs text-status-completed">
          Deleted {projectResult.projects} project{projectResult.projects === 1 ? "" : "s"} and{" "}
          {projectResult.jobs} job{projectResult.jobs === 1 ? "" : "s"}.
        </div>
      )}
    </div>
  );
}

/**
 * The account panel every signed-in user gets, admin or not.
 *
 * Uses Flyout rather than AdminPanel's centred dialog: this is the app's
 * existing slide-in convention (HelpFlyout is the other consumer), and an
 * 88vh modal would be absurd for one three-field form.
 *
 * The `if (!user)` guard is what keeps this off no-auth local-dev
 * deployments -- there the auth router is never mounted at all, so
 * /api/auth/change-password would simply 404. UserMenu carries the same guard
 * on the trigger.
 *
 * Bug reporting used to live here as a second section. It now has its own
 * menu entry and its own flyout (see BugReportFlyout), because buried under
 * "Account settings" it was effectively unreachable for the admins most likely
 * to need it.
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
        Danger zone
      </h3>
      <SelfDangerZone />
    </Flyout>
  );
}

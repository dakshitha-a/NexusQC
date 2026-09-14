import { useEffect, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { AlertTriangle, CheckCircle2, GitCommitHorizontal, Link2, Radio, Users } from "lucide-react";
import * as api from "../lib/api";
import { ApiError } from "../lib/api";
import { publicUrlSourceLabel } from "../lib/links";
import { DeployControls } from "./DeployControls";

// A commit is shown as twelve characters everywhere in this panel. Long enough
// to be unambiguous in this repository, short enough to sit in a table cell,
// and the same width update.sh and the tracker use, so the three can be
// compared by eye without anybody reformatting anything.
function short(sha: string) {
  return sha === "unknown" ? "unknown" : sha.slice(0, 12);
}

function Row({ label, value, hint, tone }: {
  label: string;
  value: string;
  hint?: string;
  tone?: "ok" | "warn";
}) {
  return (
    <div className="flex items-baseline justify-between gap-4 border-b border-border py-2 last:border-b-0">
      <div className="min-w-0">
        <div className="text-xs font-medium text-text">{label}</div>
        {hint && <div className="text-2xs text-text-muted">{hint}</div>}
      </div>
      <code
        className={
          "shrink-0 font-mono text-2xs " +
          (tone === "warn" ? "text-status-failed" : tone === "ok" ? "text-status-running" : "text-text-muted")
        }
      >
        {value}
      </code>
    </div>
  );
}

/** The address other people use to reach this deployment, which every
 *  invite and reset link is built on. Three sources (this field, .env, the
 *  browser's own origin) and the label says which is in effect; see
 *  lib/links.ts for why the browser's origin is the wrong base on a shared
 *  tailnet node. Validation is the server's (an origin, nothing after it);
 *  its message is shown here as is. */
function PublicAddress({
  onMutationSuccess,
  onMutationError,
}: {
  onMutationSuccess: () => void;
  onMutationError: (e: unknown) => void;
}) {
  const configQuery = useQuery({ queryKey: ["admin", "config"], queryFn: api.getAdminConfig });
  const cfg = configQuery.data;
  const [draft, setDraft] = useState("");
  const [error, setError] = useState<string | null>(null);
  // The field shows the effective value until the admin starts typing.
  useEffect(() => {
    setDraft(cfg?.public_url ?? "");
  }, [cfg?.public_url]);

  const save = useMutation({
    mutationFn: (value: string) => api.patchAdminConfig("public_url", value),
    onSuccess: () => {
      setError(null);
      onMutationSuccess();
    },
    onError: (e: unknown) => {
      setError(e instanceof ApiError ? e.message : String(e));
      onMutationError(e);
    },
  });

  return (
    <section>
      <h3 className="mb-1 flex items-center gap-1.5 text-xs font-semibold text-text">
        <Link2 size={13} /> Public address
      </h3>
      <p className="mb-2 text-2xs text-text-muted">
        The address other people use to reach this deployment. Every invite and password-reset
        link is built on it. On a host shared over Tailscale with each user, that is the tailnet
        name (<code className="font-mono">host.tailnet.ts.net</code>), which resolves for every
        recipient where an IP address does not. The host name must also be in the certificate
        (<code className="font-mono">QC_AGENT_CERT_FQDN</code>, or it is added from{" "}
        <code className="font-mono">QC_AGENT_PUBLIC_URL</code>).
      </p>
      {!cfg ? (
        <div className="text-xs text-text-muted">Loading...</div>
      ) : (
        <div className="rounded border border-border px-3 py-2">
          <div className="flex flex-wrap items-center gap-2">
            <input
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              placeholder="https://host.tailnet.ts.net:8443"
              data-testid="public-url-input"
              spellCheck={false}
              className="min-w-0 flex-1 rounded border border-border bg-surface-raised px-2 py-1 font-mono text-2xs text-text placeholder:text-text-muted focus:border-accent focus:outline-none"
            />
            <button
              onClick={() => save.mutate(draft)}
              disabled={save.isPending || draft.trim() === cfg.public_url}
              data-testid="public-url-save"
              className="rounded border border-border px-2 py-1 text-2xs text-text-muted hover:bg-surface-raised hover:text-text disabled:opacity-40"
            >
              Save
            </button>
            <button
              onClick={() => save.mutate("")}
              disabled={save.isPending || cfg.public_url_source !== "setting"}
              data-testid="public-url-clear"
              title="Remove the console's value; .env or the browser address applies again"
              className="rounded border border-border px-2 py-1 text-2xs text-text-muted hover:bg-surface-raised hover:text-text disabled:opacity-40"
            >
              Clear
            </button>
          </div>
          <div className="mt-1.5 text-2xs text-text-muted" data-testid="public-url-source">
            {cfg.public_url ? (
              <>
                In effect: <code className="font-mono text-text">{cfg.public_url}</code> (
                {publicUrlSourceLabel(cfg.public_url_source)})
              </>
            ) : (
              <>In effect: {publicUrlSourceLabel(cfg.public_url_source)}</>
            )}
          </div>
          {error && (
            <div className="mt-1 text-2xs text-status-failed" data-testid="public-url-error">
              {error}
            </div>
          )}
        </div>
      )}
    </section>
  );
}

export function DeploymentSection({
  onMutationSuccess,
  onMutationError,
}: {
  onMutationSuccess: () => void;
  onMutationError: (e: unknown) => void;
}) {
  const deployment = useQuery({
    queryKey: ["admin", "deployment"],
    queryFn: api.getAdminDeployment,
  });
  // Polled: the point of this table is that it is true right now, at the
  // moment somebody is deciding whether to interrupt people.
  const activity = useQuery({
    queryKey: ["admin", "activity"],
    queryFn: api.getAdminActivity,
    refetchInterval: 5000,
  });

  const apiCommit = deployment.data?.api_commit ?? "";
  const tabCommit = api.BUILD_SHA;
  // Only a comparison between two commits we actually know is meaningful.
  // 'unknown' is what an unstamped hand-run build produces, and reporting that
  // as a mismatch would tell people to reload for no reason.
  const bothKnown = Boolean(apiCommit) && apiCommit !== "unknown" && tabCommit !== "unknown";
  const tabIsStale = bothKnown && apiCommit !== tabCommit;

  const totals = activity.data?.totals;
  const unowned = activity.data?.unowned;
  const busy = activity.data?.users.filter((u) => u.would_be_interrupted || u.pending_jobs > 0) ?? [];
  // Having the admin panel open is itself an open stream, so without this
  // every deployment would permanently claim somebody is working. What should
  // give an admin pause is everybody else -- and a running job of their own,
  // which still counts, because a restart kills it whoever started it.
  const othersInterrupted = totals?.others_interrupted ?? 0;

  return (
    <div className="space-y-5">
      <PublicAddress onMutationSuccess={onMutationSuccess} onMutationError={onMutationError} />

      <section>
        <h3 className="mb-1 flex items-center gap-1.5 text-xs font-semibold text-text">
          <GitCommitHorizontal size={13} /> What is running
        </h3>
        <p className="mb-2 text-2xs text-text-muted">
          The api reports the commit baked into its image. This tab reports the commit its
          own bundle was compiled from. They are built together, so they should agree; if
          they do not, this tab has been open across an update.
        </p>
        <div className="rounded border border-border bg-surface px-3">
          <Row
            label="API"
            hint={
              deployment.data?.api_commit_known
                ? "from the image's QC_AGENT_BUILD_COMMIT"
                : "built by hand with no stamp passed, so it cannot say"
            }
            value={deployment.isLoading ? "…" : short(apiCommit)}
            tone={deployment.data?.api_commit_known ? "ok" : "warn"}
          />
          <Row
            label="This browser tab"
            hint="baked into the bundle at build time"
            value={short(tabCommit)}
            tone={tabIsStale ? "warn" : undefined}
          />
        </div>
        {tabIsStale && (
          <div className="mt-2 flex items-start gap-2 rounded border border-status-failed/40 bg-status-failed/5 px-3 py-2 text-2xs text-text">
            <AlertTriangle size={13} className="mt-px shrink-0 text-status-failed" />
            <div>
              This tab is running an older build than the server.{" "}
              <button
                onClick={() => window.location.reload()}
                className="underline underline-offset-2"
              >
                Reload
              </button>{" "}
              to pick up the current one.
            </div>
          </div>
        )}
      </section>

      <section>
        <h3 className="mb-1 flex items-center gap-1.5 text-xs font-semibold text-text">
          <Users size={13} /> Who is working right now
        </h3>
        <p className="mb-2 text-2xs text-text-muted">
          Restarting the API kills every running calculation. This is who that would
          affect, counted from the job files on disk and the live event streams rather
          than from when anybody last logged in.
        </p>

        {activity.isLoading ? (
          <div className="rounded border border-border bg-surface px-3 py-6 text-center text-2xs text-text-muted">
            checking…
          </div>
        ) : (
          <>
            <div className="mb-2 grid grid-cols-3 gap-2">
              {[
                { label: "running jobs", value: totals?.running_jobs ?? 0, warn: true },
                { label: "queued jobs", value: totals?.pending_jobs ?? 0, warn: false },
                { label: "open streams", value: totals?.open_streams ?? 0, warn: true },
              ].map((s) => (
                <div key={s.label} className="rounded border border-border bg-surface px-3 py-2">
                  <div
                    className={
                      "font-mono text-lg tabular-nums " +
                      (s.warn && s.value > 0 ? "text-status-running" : "text-text")
                    }
                  >
                    {s.value}
                  </div>
                  <div className="text-2xs text-text-muted">{s.label}</div>
                </div>
              ))}
            </div>

            {othersInterrupted === 0 && (totals?.running_jobs ?? 0) === 0 ? (
              <div className="flex items-center gap-2 rounded border border-border bg-surface px-3 py-3 text-2xs text-text-muted">
                <CheckCircle2 size={13} className="text-status-running" />
                Nobody else has a job running or a stream open. Restarting now interrupts no one.
              </div>
            ) : (
              <div className="rounded border border-border bg-surface px-3">
                {busy.map((u) => (
                  <div
                    key={u.id}
                    className="flex items-center justify-between gap-3 border-b border-border py-2 last:border-b-0"
                  >
                    <div className="min-w-0">
                      <div className="truncate text-xs text-text">
                        {u.username ?? u.id}
                        {u.is_you && (
                          <span className="ml-1.5 text-3xs font-normal text-text-muted">(you)</span>
                        )}
                      </div>
                      <div className="text-2xs text-text-muted">{u.email}</div>
                    </div>
                    <div className="flex shrink-0 items-center gap-3 font-mono text-2xs tabular-nums text-text-muted">
                      {u.running_jobs > 0 && (
                        <span className="text-status-running">{u.running_jobs} running</span>
                      )}
                      {u.pending_jobs > 0 && <span>{u.pending_jobs} queued</span>}
                      {u.open_streams > 0 && (
                        <span className="flex items-center gap-1">
                          <Radio size={11} /> {u.open_streams}
                        </span>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            )}

            {/* Jobs submitted outside any conversation carry no owner at all,
                so they cannot be attributed to a person -- but they still
                occupy the machine and an update still kills them. */}
            {(unowned?.running_jobs || unowned?.pending_jobs || unowned?.open_streams) ? (
              <div className="mt-2 text-2xs text-text-muted">
                Plus {unowned.running_jobs} running and {unowned.pending_jobs} queued with no
                recorded owner, which nobody will be told about.
              </div>
            ) : null}
          </>
        )}
      </section>

      <DeployControls
        deployment={deployment.data}
        activity={activity.data}
        onMutationSuccess={onMutationSuccess}
        onMutationError={onMutationError}
      />
    </div>
  );
}

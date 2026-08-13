import * as Dialog from "@radix-ui/react-dialog";
import { X } from "lucide-react";
import { useJobQuery } from "../lib/queries";
import { StatusLabel } from "./StatusDot";
import { KillButton } from "./KillButton";
import { UvVisPanel } from "./UvVisPanel";
import { MoCubeViewer } from "./MoCubeViewer";
import { VibrationTable } from "./VibrationTable";
import { LiveLogPanel } from "./LiveLogPanel";

function SummaryValue({ value }: { value: unknown }) {
  if (Array.isArray(value)) {
    return <span className="font-mono">[{value.map((v) => (typeof v === "number" ? v.toFixed(4) : String(v))).join(", ")}]</span>;
  }
  if (typeof value === "number") return <span className="font-mono">{Number.isInteger(value) ? value : value.toFixed(6)}</span>;
  return <span className="font-mono">{String(value)}</span>;
}

export function JobDetailDrawer({
  jobId,
  threadId,
  onClose,
}: {
  jobId: string;
  threadId?: string;
  onClose: () => void;
}) {
  const { data: job } = useJobQuery(jobId);

  return (
    <Dialog.Root open onOpenChange={(open) => !open && onClose()}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-40 bg-black/50" />
        <Dialog.Content className="fixed right-0 top-0 z-50 flex h-full w-105 max-w-[90vw] flex-col border-l border-border bg-surface shadow-2xl">
          {!job ? (
            <div className="p-4 text-sm text-text-muted">Loading...</div>
          ) : (
            <>
              <div className="flex items-start justify-between border-b border-border px-4 py-3">
                <div>
                  <Dialog.Title className="font-mono text-sm text-text">{job.job_id}</Dialog.Title>
                  <div className="mt-1 text-xs text-text-muted">
                    <StatusLabel status={job.status} />
                  </div>
                </div>
                <div className="flex items-center gap-1">
                  <KillButton job={job} threadId={threadId} />
                  <Dialog.Close className="rounded p-1.5 text-text-muted hover:bg-surface-raised hover:text-text">
                    <X size={15} />
                  </Dialog.Close>
                </div>
              </div>

              <div className="flex-1 overflow-y-auto px-4 py-3 text-sm">
                <div className="mb-4">
                  <div className="mb-1 text-xs font-medium uppercase tracking-wide text-text-muted">
                    {job.method} &middot; {job.engine}
                  </div>
                  {job.retried_from && (
                    <div className="mb-2 rounded border border-status-running/40 bg-status-running/10 px-2 py-1 text-xs text-status-running">
                      Retry {job.retry_count} of previous job {job.retried_from}
                    </div>
                  )}
                  <div className="text-xs text-text-muted">{job.message}</div>
                </div>

                {job.status === "running" && (
                  <div className="mb-4">
                    <LiveLogPanel jobId={job.job_id} />
                  </div>
                )}

                <div className="mb-4">
                  <div className="mb-1.5 text-xs font-medium uppercase tracking-wide text-text-muted">Parameters</div>
                  <table className="w-full text-xs">
                    <tbody>
                      {Object.entries(job.params).map(([k, v]) => (
                        <tr key={k} className="border-t border-border">
                          <td className="py-1 pr-3 text-text-muted">{k}</td>
                          <td className="py-1">
                            <SummaryValue value={v} />
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>

                {job.error && (
                  <div className="mb-4">
                    <div className="mb-1.5 text-xs font-medium uppercase tracking-wide text-status-failed">Error</div>
                    <pre className="max-h-64 overflow-y-auto whitespace-pre-wrap rounded border border-status-failed/30 bg-status-failed/5 p-2 font-mono text-[11px] text-status-failed">
                      {job.error}
                    </pre>
                  </div>
                )}

                {job.summary && Object.keys(job.summary).length > 0 && (
                  <div className="mb-4">
                    <div className="mb-1.5 text-xs font-medium uppercase tracking-wide text-text-muted">Summary</div>
                    <table className="w-full text-xs">
                      <tbody>
                        {Object.entries(job.summary)
                          .filter(([k]) => k !== "normal_modes" && k !== "frequencies_cm-1")
                          .map(([k, v]) => (
                            <tr key={k} className="border-t border-border">
                              <td className="py-1 pr-3 text-text-muted">{k}</td>
                              <td className="py-1">
                                <SummaryValue value={v} />
                              </td>
                            </tr>
                          ))}
                      </tbody>
                    </table>
                  </div>
                )}

                {Array.isArray(job.summary?.["frequencies_cm-1"]) && (
                  <div className="mb-4">
                    <div className="mb-1.5 text-xs font-medium uppercase tracking-wide text-text-muted">
                      Vibrational frequencies
                    </div>
                    <VibrationTable frequenciesCm1={job.summary["frequencies_cm-1"] as number[]} />
                  </div>
                )}

                {job.artifacts?.uvvis_spectrum && (
                  <div className="mb-4">
                    <div className="mb-1.5 text-xs font-medium uppercase tracking-wide text-text-muted">UV/Vis spectrum</div>
                    <UvVisPanel jobId={job.job_id} />
                  </div>
                )}

                {job.artifacts?.cubes && Object.keys(job.artifacts.cubes as object).length > 0 && (
                  <div className="mb-4">
                    <div className="mb-1.5 text-xs font-medium uppercase tracking-wide text-text-muted">Molecular orbitals</div>
                    <MoCubeViewer jobId={job.job_id} cubeLabels={Object.keys(job.artifacts.cubes as object)} />
                  </div>
                )}
              </div>
            </>
          )}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

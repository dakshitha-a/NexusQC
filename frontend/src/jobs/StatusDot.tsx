import type { JobRow } from "../lib/api";

const COLOR: Record<JobRow["status"], string> = {
  pending: "bg-status-pending",
  running: "bg-status-running",
  completed: "bg-status-completed",
  failed: "bg-status-failed",
  cancelled: "bg-status-cancelled",
};

export function StatusDot({ status }: { status: JobRow["status"] }) {
  return (
    <span className="relative flex h-2 w-2 shrink-0">
      {status === "running" && (
        <span className={`absolute inline-flex h-full w-full animate-ping rounded-full ${COLOR[status]} opacity-60`} />
      )}
      <span className={`relative inline-flex h-2 w-2 rounded-full transition-colors duration-base ease-standard ${COLOR[status]}`} />
    </span>
  );
}

export function StatusLabel({ status }: { status: JobRow["status"] }) {
  return (
    <span className="flex items-center gap-1.5">
      <StatusDot status={status} />
      <span className="capitalize">{status}</span>
    </span>
  );
}

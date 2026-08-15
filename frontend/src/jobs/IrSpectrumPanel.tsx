import { jobArtifactUrl } from "../lib/api";

export function IrSpectrumPanel({ jobId }: { jobId: string }) {
  return (
    <img
      src={jobArtifactUrl(jobId, "ir_spectrum")}
      alt="IR spectrum"
      className="w-full rounded border border-border bg-white"
    />
  );
}

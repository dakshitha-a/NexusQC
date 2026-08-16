import { useState } from "react";
import { jobArtifactUrl } from "../lib/api";

export function IrSpectrumPanel({ jobId }: { jobId: string }) {
  const [failed, setFailed] = useState(false);

  if (failed) {
    return <div className="text-xs text-status-failed">IR spectrum image failed to load.</div>;
  }

  return (
    <img
      src={jobArtifactUrl(jobId, "ir_spectrum")}
      alt="IR spectrum"
      onError={() => setFailed(true)}
      className="w-full rounded border border-border bg-white"
    />
  );
}

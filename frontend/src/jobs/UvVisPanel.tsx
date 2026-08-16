import { useState } from "react";
import { jobArtifactUrl } from "../lib/api";

export function UvVisPanel({ jobId }: { jobId: string }) {
  const [failed, setFailed] = useState(false);

  if (failed) {
    return <div className="text-xs text-status-failed">UV/Vis spectrum image failed to load.</div>;
  }

  return (
    <img
      src={jobArtifactUrl(jobId, "uvvis_spectrum")}
      alt="UV/Vis spectrum"
      onError={() => setFailed(true)}
      className="w-full rounded border border-border bg-white"
    />
  );
}

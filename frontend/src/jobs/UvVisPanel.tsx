import { jobArtifactUrl } from "../lib/api";

export function UvVisPanel({ jobId }: { jobId: string }) {
  return (
    <img
      src={jobArtifactUrl(jobId, "uvvis_spectrum")}
      alt="UV/Vis spectrum"
      className="w-full rounded border border-border bg-white"
    />
  );
}

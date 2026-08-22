import { useState } from "react";
import { DownloadButton } from "../app-shell/DownloadButton";
import { ViewerOverlay } from "../app-shell/ExpandablePanel";
import { jobArtifactUrl } from "../lib/api";
import { triggerDownload } from "../lib/download";

export function IrSpectrumPanel({ jobId }: { jobId: string }) {
  const [failed, setFailed] = useState(false);
  const [downloadError, setDownloadError] = useState<string | null>(null);

  if (failed) {
    return <div className="text-xs text-status-failed">IR spectrum image failed to load.</div>;
  }

  return (
    <div className="relative">
      <ViewerOverlay>
        <DownloadButton
          title="Download this spectrum as a PNG"
          testId="ir-download-png"
          className="bg-surface/70 backdrop-blur-sm"
          // Same reasoning as UvVisPanel: already a server-rendered PNG
          // (render_ir_spectrum_plot) at a real URL, not a canvas capture.
          onDownload={() => triggerDownload(jobArtifactUrl(jobId, "ir_spectrum"))}
          onError={setDownloadError}
        />
      </ViewerOverlay>
      <img
        src={jobArtifactUrl(jobId, "ir_spectrum")}
        alt="IR spectrum"
        onError={() => setFailed(true)}
        className="w-full rounded border border-border bg-white"
      />
      {downloadError && <div className="mt-1 text-xs text-status-failed">{downloadError}</div>}
    </div>
  );
}

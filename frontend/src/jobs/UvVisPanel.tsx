import { useState } from "react";
import { DownloadButton } from "../app-shell/DownloadButton";
import { ViewerOverlay } from "../app-shell/ExpandablePanel";
import { jobArtifactUrl } from "../lib/api";
import { triggerDownload } from "../lib/download";

export function UvVisPanel({ jobId }: { jobId: string }) {
  const [failed, setFailed] = useState(false);
  const [downloadError, setDownloadError] = useState<string | null>(null);

  if (failed) {
    return <div className="text-xs text-status-failed">UV/Vis spectrum image failed to load.</div>;
  }

  return (
    <div className="relative">
      <ViewerOverlay>
        <DownloadButton
          title="Download this spectrum as a PNG"
          testId="uvvis-download-png"
          className="bg-surface/70 backdrop-blur-sm"
          // The image is already a server-rendered PNG (render_uvvis_plot,
          // app/chemistry/spectrum.py) at a real URL, not a canvas capture
          // -- triggerDownload (lib/download.ts) covers exactly this case,
          // same as every other API-route download in this app.
          onDownload={() => triggerDownload(jobArtifactUrl(jobId, "uvvis_spectrum"), `${jobId}_uvvis_spectrum.png`)}
          onError={setDownloadError}
        />
      </ViewerOverlay>
      <img
        src={jobArtifactUrl(jobId, "uvvis_spectrum")}
        alt="UV/Vis spectrum"
        onError={() => setFailed(true)}
        className="w-full rounded border border-border bg-white"
      />
      {downloadError && <div className="mt-1 text-xs text-status-failed">{downloadError}</div>}
    </div>
  );
}

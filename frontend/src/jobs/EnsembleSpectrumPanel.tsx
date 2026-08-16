import { useState } from "react";
import { Download } from "lucide-react";
import { jobArtifactUrl } from "../lib/api";

/** Static image + raw-data download for a wigner_ensemble master's pooled
 * nuclear-ensemble spectrum (artifacts.ensemble_spectrum/
 * ensemble_spectrum_data) -- written automatically by EnsembleOrchestrator
 * once every sample completes, and re-written in place (same artifact
 * key) whenever plot_wigner_ensemble_spectrum re-plots at a different
 * FWHM, so this panel always reflects whatever was rendered last. Mirrors
 * UvVisPanel's shape. */
export function EnsembleSpectrumPanel({ jobId }: { jobId: string }) {
  const [failed, setFailed] = useState(false);

  if (failed) {
    return <div className="text-xs text-status-failed">Ensemble spectrum image failed to load.</div>;
  }

  return (
    <div className="flex flex-col gap-1.5">
      <img
        src={jobArtifactUrl(jobId, "ensemble_spectrum")}
        alt="Nuclear-ensemble absorption spectrum"
        onError={() => setFailed(true)}
        className="w-full rounded border border-border bg-white"
      />
      <a
        href={jobArtifactUrl(jobId, "ensemble_spectrum_data")}
        download
        className="flex w-fit items-center gap-1.5 text-xs text-text-muted hover:text-text"
      >
        <Download size={12} />
        Download raw spectral data (.dat)
      </a>
    </div>
  );
}

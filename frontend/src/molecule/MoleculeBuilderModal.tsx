import * as Dialog from "@radix-ui/react-dialog";
import { X } from "lucide-react";
import { useCallback, useRef, useState } from "react";
import { Editor } from "ketcher-react";
// The package's default entry point ("ketcher-standalone") resolves to a
// build that inlines the Indigo wasm binary as a base64 string INSIDE the
// JS bundle -- 21MB of it, which is why this file's own lazy chunk (already
// split off by MoleculePanel.tsx's React.lazy) measured 28.7MB / 8.5MB
// gzipped, larger than every other chunk in the app combined. The package
// ships an alternate entry, "ketcher-standalone/dist/binaryWasm", built
// from the same source (see its package.json's "exports" map) that instead
// ships the wasm as a real .wasm asset loaded by a Web Worker -- the
// driver JS alone drops to ~40KB. Same exported class, same constructor
// signature (confirmed against both entries' .d.ts), so this is a pure
// swap of which prebuilt artifact gets bundled, not a behavior change.
import { StandaloneStructServiceProvider } from "ketcher-standalone/dist/binaryWasm";
import type { Ketcher } from "ketcher-core";
import "ketcher-react/dist/index.css";
import * as api from "../lib/api";
import type { ThreadState } from "../lib/api";

// One indigo-wasm service instance for the life of the app -- Ketcher
// runs entirely client-side (no Java/Indigo backend service), so this is
// cheap to keep around rather than re-instantiating per modal open.
const structServiceProvider = new StandaloneStructServiceProvider();

// The 2D-sketcher molecule builder: draw a structure with Ketcher, then
// "Use this structure" sends the exported molfile to the backend, which
// reads the topology with RDKit, adds explicit hydrogens, and runs
// ETKDG distance geometry + an MMFF94 (falling back to UFF) optimization
// to produce a relaxed 3D conformer -- added as the newest, active frame
// in the molecule panel (see molecule_from_molblock/add_built_frame).
// Ketcher's own 2D coordinates are discarded server-side; only the
// connection table (bonds, formal charges, stereo) is read.
export function MoleculeBuilderModal({
  threadId,
  onClose,
  onBuilt,
}: {
  threadId: string;
  onClose: () => void;
  onBuilt: (state: ThreadState) => void;
}) {
  const ketcherRef = useRef<Ketcher | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Stable across re-renders (setBusy/setError in handleUse below re-render
  // this component while the editor stays mounted) -- ketcher-react's
  // init effect depends on these props by reference, so a fresh inline
  // function literal on every render tore the whole editor down and
  // rebuilt it (wiping whatever was on the canvas) the moment handleUse's
  // own setBusy(true) fired, before getMolfile() ever ran. Same class of
  // bug as MoleculeViewer.tsx's React 18 Strict Mode double-invoke note
  // in CLAUDE.md, different manifestation (a prop-identity-triggered
  // remount here, not a duplicate WebGL context).
  const handleKetcherInit = useCallback((ketcher: Ketcher) => {
    ketcherRef.current = ketcher;
  }, []);
  const handleKetcherError = useCallback((msg: string) => setError(String(msg)), []);

  const handleUse = async () => {
    const ketcher = ketcherRef.current;
    if (!ketcher) return;
    setError(null);
    setBusy(true);
    try {
      const molblock = await ketcher.getMolfile();
      const state = await api.buildMolecule(threadId, molblock);
      onBuilt(state);
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog.Root open onOpenChange={(o) => !o && onClose()}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-40 bg-black/50 data-[state=open]:animate-fade-in" />
        <Dialog.Content className="fixed left-1/2 top-1/2 z-50 flex h-[85vh] w-[92vw] max-w-5xl -translate-x-1/2 -translate-y-1/2 flex-col overflow-hidden rounded-lg border border-border bg-surface shadow-2xl data-[state=open]:animate-fade-in">
          <div className="flex items-center justify-between border-b border-border px-4 py-3">
            <div>
              <Dialog.Title className="text-sm font-semibold text-text">Build molecule</Dialog.Title>
              <div className="text-xs text-text-muted">
                Draw a structure, then generate a relaxed 3D conformer from it.
              </div>
            </div>
            <Dialog.Close className="rounded p-1.5 text-text-muted hover:bg-surface-raised hover:text-text">
              <X size={15} />
            </Dialog.Close>
          </div>
          <div className="relative min-h-0 flex-1 bg-white">
            <Editor
              staticResourcesUrl=""
              structServiceProvider={structServiceProvider}
              errorHandler={handleKetcherError}
              onInit={handleKetcherInit}
            />
          </div>
          <div className="flex items-center justify-between gap-3 border-t border-border px-4 py-3">
            <div className="min-h-4 text-xs text-status-failed">{error}</div>
            <div className="flex items-center gap-2">
              <button
                onClick={onClose}
                className="rounded border border-border px-3 py-1.5 text-xs text-text-muted hover:text-text"
              >
                Cancel
              </button>
              <button
                onClick={handleUse}
                disabled={busy}
                className="rounded bg-accent px-3 py-1.5 text-xs font-medium text-white disabled:opacity-50"
              >
                {busy ? "Generating 3D conformer..." : "Use this structure"}
              </button>
            </div>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

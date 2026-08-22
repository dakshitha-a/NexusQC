import { useEffect, useRef, useState } from "react";
import type { DragEvent } from "react";
import { Send, CircleStop, Loader2, Plus } from "lucide-react";
import { useQueryClient } from "@tanstack/react-query";
import { useAttachedJobsStore } from "../lib/attachedJobsStore";
import { useAttachedFrameStore } from "../lib/attachedFrameStore";
import { useAttachedPlotsStore } from "../lib/attachedPlotsStore";
import { useComposerDraftStore } from "../lib/composerDraftStore";
import { useActiveThreadStore } from "../lib/activeThreadStore";
import { useChatStore } from "../lib/chatStore";
import { jobsListQueryKey, jobsQueryKey, uploadsQuotaQueryKey, uploadsQueryKey } from "../lib/queries";
import * as api from "../lib/api";

const UPLOAD_EXTENSIONS = [".xyz", ".inp", ".input", ".json"];
function hasUploadExtension(filename: string): boolean {
  const lower = filename.toLowerCase();
  return UPLOAD_EXTENSIONS.some((ext) => lower.endsWith(ext));
}

interface Props {
  disabled: boolean;
  disabledReason?: string;
  onSend: (text: string, jobIds: string[], frameId: string | null, plotIds: string[]) => void;
  turnInProgress: boolean;
  onStop: () => void;
  /** True from the moment Stop is clicked until the turn actually ends --
   * see ChatPane's stopRequested state for why this is tracked separately
   * from turnInProgress (the backend can take a few seconds to unwind a
   * turn that's mid-tool-call). Disables the button so repeated clicks
   * are inert instead of silently doing nothing, and swaps the icon so
   * the click visibly registered. */
  stopRequested: boolean;
}

export function Composer({ disabled, disabledReason, onSend, turnInProgress, onStop, stopRequested }: Props) {
  const [text, setText] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const { attachedJobs, removeJob, clear } = useAttachedJobsStore();
  const { attachedFrame, clearAttachedFrame } = useAttachedFrameStore();
  const { attachedPlots, removePlot, clear: clearAttachedPlots } = useAttachedPlotsStore();
  const { draft, nonce, clearDraft } = useComposerDraftStore();
  const activeThreadId = useActiveThreadStore((s) => s.activeThreadId);
  const setMolecule = useChatStore((s) => s.setMolecule);
  const setMoleculeFrames = useChatStore((s) => s.setMoleculeFrames);
  const applyEvent = useChatStore((s) => s.applyEvent);
  const queryClient = useQueryClient();
  const [uploadState, setUploadState] = useState<"idle" | "pending">("idle");
  const [uploadNote, setUploadNote] = useState<string | null>(null);
  const [dragOver, setDragOver] = useState(false);

  // The composer's own shortcut for the same upload-then-attach flow
  // FilesSection offers from the sidebar (Phase 3's "composer + button"):
  // uploads each file, then -- only for a .xyz whose sniff makes it
  // attachable -- immediately attaches it into this conversation, so
  // dropping a geometry straight onto the chat box is one motion instead
  // of two panels. A non-.xyz upload (blind engine input) is added to
  // Files but not auto-attached; there is no attach semantics for it yet
  // (raw_input_text is still a pasted chat parameter -- see
  // app/agent/registry2/params.py), so it's left for the user to open via
  // the Files panel.
  const handleFiles = async (files: File[]) => {
    if (files.length === 0) return;
    const accepted = files.filter((f) => hasUploadExtension(f.name));
    const rejected = files.length - accepted.length;
    if (accepted.length === 0) {
      setUploadNote(rejected > 0 ? "Only XYZ, INP, INPUT, and JSON files can be uploaded here." : null);
      return;
    }
    setUploadState("pending");
    setUploadNote(null);
    const notes: string[] = [];
    for (const file of accepted) {
      try {
        const record = await api.addUpload(file);
        if (record.extension === ".xyz" && activeThreadId) {
          const result = await api.attachUpload(activeThreadId, record.id);
          if (result.kind === "frames" && result.state) {
            setMolecule(result.state.molecule);
            setMoleculeFrames(result.state.molecule_frames);
            notes.push(`${file.name} attached.`);
          } else if (result.kind === "geometry_set") {
            if (result.message) applyEvent({ type: "message", message: result.message });
            queryClient.invalidateQueries({ queryKey: jobsListQueryKey });
            queryClient.invalidateQueries({ queryKey: jobsQueryKey(activeThreadId) });
            notes.push(`${file.name} became a geometry set (see the conversation).`);
          }
        } else if (record.extension === ".xyz") {
          notes.push(`${file.name} added to Files -- open a conversation to attach it.`);
        } else {
          notes.push(`${file.name} added to Files.`);
        }
      } catch (err) {
        notes.push(`${file.name}: ${String(err)}`);
      }
    }
    queryClient.invalidateQueries({ queryKey: uploadsQueryKey });
    queryClient.invalidateQueries({ queryKey: uploadsQuotaQueryKey });
    setUploadState("idle");
    setUploadNote(notes.join(" "));
  };

  const handleDrop = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setDragOver(false);
    void handleFiles(Array.from(e.dataTransfer.files ?? []));
  };

  // Accept a prefill from elsewhere (the welcome screen's example prompts).
  // Keyed on `nonce`, not `draft`: clicking the same example twice leaves the
  // text identical, and an effect keyed on the text would not re-fire.
  useEffect(() => {
    if (draft === null) return;
    setText(draft);
    clearDraft();
    const el = textareaRef.current;
    if (!el) return;
    el.focus();
    // Wait for the value prop to land before measuring or placing the caret.
    requestAnimationFrame(() => {
      el.selectionStart = el.selectionEnd = el.value.length;
      resizeToContent(el);
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [nonce]);

  // Stop is confirmed (server/routes/chat.py) to only take effect at the
  // next safe checkpoint -- it cannot abort a tool call already in flight,
  // so "Stopping..." can sit for however long that tool takes (seconds,
  // typically, but unbounded in principle). Past a few seconds this stops
  // looking like "in progress" and starts looking like "frozen," so add an
  // explanatory hint rather than leaving the spinner to speak for itself.
  const [showFinishingHint, setShowFinishingHint] = useState(false);
  useEffect(() => {
    if (!stopRequested) {
      setShowFinishingHint(false);
      return;
    }
    const t = setTimeout(() => setShowFinishingHint(true), 3000);
    return () => clearTimeout(t);
  }, [stopRequested]);

  // Auto-grow: reset to "auto" first so scrollHeight reflects the
  // content's actual height (not the previously-set fixed height), then
  // set the height to match. max-h-40 in the className below still caps
  // it visually and lets it scroll past that.
  const resizeToContent = (el: HTMLTextAreaElement | null) => {
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${el.scrollHeight}px`;
  };

  const send = () => {
    const trimmed = text.trim();
    if (!trimmed || disabled) return;
    onSend(
      trimmed,
      attachedJobs.map((j) => j.job_id),
      attachedFrame?.frame_id ?? null,
      attachedPlots.map((p) => p.plot_id),
    );
    setText("");
    clear();
    clearAttachedFrame();
    clearAttachedPlots();
    // Textarea content clears via the value prop, but height doesn't
    // auto-shrink without a re-measure -- reset it explicitly.
    if (textareaRef.current) textareaRef.current.style.height = "auto";
  };

  return (
    <div
      className={`shrink-0 border-t border-border p-3 ${dragOver ? "bg-accent/5" : ""}`}
      onDragOver={(e) => {
        e.preventDefault();
        setDragOver(true);
      }}
      onDragLeave={() => setDragOver(false)}
      onDrop={handleDrop}
    >
      <input
        ref={fileInputRef}
        type="file"
        accept=".xyz,.inp,.input,.json"
        multiple
        className="hidden"
        data-testid="composer-file-input"
        onChange={(e) => {
          void handleFiles(Array.from(e.target.files ?? []));
          e.target.value = "";
        }}
      />
      {uploadNote && (
        <div className="mb-1.5 text-xs text-text-muted" data-testid="composer-upload-note">
          {uploadNote}
        </div>
      )}
      {(attachedJobs.length > 0 || attachedFrame || attachedPlots.length > 0) && (
        <div className="mb-1.5 flex flex-wrap gap-1">
          {attachedJobs.map((j) => (
            <span
              key={j.job_id}
              className="flex items-center gap-1 rounded-full bg-accent-muted px-2 py-0.5 text-[11px] text-text"
            >
              {j.label}
              <button
                onClick={() => removeJob(j.job_id)}
                data-testid={`composer-detach-job-${j.job_id}`}
                className="text-text-muted hover:text-text"
                title="Detach job from prompt"
              >
                &times;
              </button>
            </span>
          ))}
          {attachedPlots.map((p) => (
            <span
              key={p.plot_id}
              className="flex items-center gap-1 rounded-full bg-accent-muted px-2 py-0.5 text-[11px] text-text"
            >
              {p.label}
              <button
                onClick={() => removePlot(p.plot_id)}
                data-testid={`composer-detach-plot-${p.plot_id}`}
                className="text-text-muted hover:text-text"
                title="Detach plot from prompt"
              >
                &times;
              </button>
            </span>
          ))}
          {attachedFrame && (
            <span className="flex items-center gap-1 rounded-full bg-accent-muted px-2 py-0.5 text-[11px] text-text">
              {attachedFrame.label}
              <button
                onClick={clearAttachedFrame}
                data-testid="composer-detach-frame"
                className="text-text-muted hover:text-text"
                title="Detach molecule frame from prompt"
              >
                &times;
              </button>
            </span>
          )}
        </div>
      )}
      {disabled && disabledReason && (
        <div className="mb-1.5 flex items-center gap-1.5 text-xs text-text-muted">
          {/^(Connecting|Lost connection)/.test(disabledReason) && <Loader2 size={11} className="animate-spin" />}
          {disabledReason}
        </div>
      )}
      {showFinishingHint && (
        <div className="mb-1.5 text-xs text-text-muted animate-fade-in">
          Finishing the current step -- Stop can't interrupt a tool call already in progress.
        </div>
      )}
      <div className="relative flex items-end gap-2 rounded-lg border border-border bg-surface px-3 py-2 focus-within:border-accent">
        {/* Decorative overlay, not the actual border -- pulses opacity on
            its own so the disabled textarea's placeholder text underneath
            stays fully legible instead of fading in and out with it. */}
        {turnInProgress && (
          <div
            aria-hidden="true"
            className="pointer-events-none absolute inset-0 animate-pulse rounded-lg border border-accent/60"
          />
        )}
        <button
          onClick={() => fileInputRef.current?.click()}
          disabled={uploadState === "pending"}
          className="shrink-0 rounded-md p-1.5 text-text-muted hover:bg-surface-raised hover:text-text disabled:opacity-40"
          title="Attach an XYZ geometry or a blind ORCA/BAGEL input file"
          data-testid="composer-add-file"
        >
          {uploadState === "pending" ? <Loader2 size={15} className="animate-spin" /> : <Plus size={15} />}
        </button>
        <textarea
          ref={textareaRef}
          value={text}
          onChange={(e) => {
            setText(e.target.value);
            resizeToContent(e.target);
          }}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              send();
            }
          }}
          disabled={disabled}
          placeholder="e.g. 'water' or 'run a CASSCF(4,4)/cc-pVDZ on formaldehyde'"
          rows={1}
          className="max-h-40 min-h-6 flex-1 resize-none overflow-y-auto bg-transparent text-sm text-text placeholder:text-text-muted outline-none disabled:opacity-50"
        />
        {turnInProgress ? (
          <button
            onClick={onStop}
            disabled={stopRequested}
            className="shrink-0 rounded-md bg-status-failed p-1.5 text-white disabled:opacity-60"
            title={stopRequested ? "Stopping..." : "Stop"}
          >
            {stopRequested ? <Loader2 size={15} className="animate-spin" /> : <CircleStop size={15} />}
          </button>
        ) : (
          <button
            onClick={send}
            disabled={disabled || !text.trim()}
            className="shrink-0 rounded-md bg-accent p-1.5 text-white disabled:opacity-30"
            title="Send"
          >
            <Send size={15} />
          </button>
        )}
      </div>
    </div>
  );
}

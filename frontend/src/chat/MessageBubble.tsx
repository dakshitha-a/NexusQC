import { useState } from "react";
import { AlertTriangle, ChevronDown, ChevronRight, Download, Wrench } from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { ChatMessage } from "../lib/api";
import { jobArtifactUrl, troubleshootJob } from "../lib/api";
import { useChatStore } from "../lib/chatStore";
import { PaperCard } from "./PaperCard";

// search_academic_literature (app/agent/scholar_search.py) joins paper
// blocks with this exact delimiter and never emits it in an error/no-
// results string (those are a single plain-text block) -- splitting on it
// is safe: an error message just yields one block, which the shape check
// below then rejects as "not paper-shaped" and falls through to the
// generic collapsed view instead of being mangled by a field-level parse.
const SCHOLAR_TOOL_NAME = "search_academic_literature";

function splitPaperBlocks(content: string): string[] | null {
  const blocks = content.split("\n\n---\n\n");
  const looksLikePapers = blocks.every((b) => b.includes("\nAuthors:") && b.includes("\nURL:"));
  return looksLikePapers ? blocks : null;
}

// plot_job_comparison (app/agent/tools.py) prepends this exact marker as
// its return value's first line so the plot can be rendered inline here
// deterministically -- not by asking the LLM to relay an image URL in its
// own reply, which ToolMessage content never renders as markdown for
// anyway (see below).
const PLOT_TOOL_NAMES = new Set(["plot_job_comparison", "plot_wigner_ensemble_spectrum"]);
const PLOT_ARTIFACT_RE = /^PLOT_ARTIFACT job_id=(\S+) key=(\S+)\n([\s\S]*)$/;

function parsePlotArtifact(content: string): { jobId: string; artifactKey: string; text: string } | null {
  const m = PLOT_ARTIFACT_RE.exec(content);
  return m ? { jobId: m[1], artifactKey: m[2], text: m[3] } : null;
}

export function HumanBubble({ content }: { content: string }) {
  return (
    <div className="flex justify-end">
      <div className="max-w-[80%] min-w-0 rounded-lg rounded-br-sm bg-accent px-3.5 py-2 text-sm text-white whitespace-pre-wrap break-words">
        {content}
      </div>
    </div>
  );
}

export function AssistantBubble({ content, streaming }: { content: string; streaming?: boolean }) {
  if (!content) return null;
  return (
    <div className="flex justify-start">
      <div className="max-w-[85%] min-w-0 rounded-lg rounded-bl-sm bg-surface px-3.5 py-2 text-sm text-text prose-invert break-words [&_p]:my-1.5 [&_ul]:my-1.5 [&_ol]:my-1.5 [&_pre]:my-2 [&_pre]:overflow-x-auto [&_pre]:rounded [&_pre]:bg-bg [&_pre]:p-2 [&_code]:font-mono [&_code]:text-[12.5px] [&_table]:my-2 [&_table]:block [&_table]:max-w-full [&_table]:overflow-x-auto [&_table]:whitespace-nowrap [&_table]:align-middle [&_th]:border [&_th]:border-border [&_th]:px-2 [&_th]:py-1 [&_td]:border [&_td]:border-border [&_td]:px-2 [&_td]:py-1">
        <ReactMarkdown remarkPlugins={[remarkGfm]}>{content}</ReactMarkdown>
        {/* Local-model token cadence is uneven -- a word can land, then
            stall for a beat before the rest arrives. Without this the
            bubble goes visually silent during that gap and reads as
            stuck; this keeps a "still working" cue alive the whole time
            a message is streaming, not just before the first token. */}
        {streaming && (
          <span
            aria-hidden="true"
            className="ml-0.5 inline-block h-3.5 w-[7px] translate-y-[3px] animate-pulse bg-accent"
          />
        )}
      </div>
    </div>
  );
}

function PlotArtifactCard({ jobId, artifactKey }: { jobId: string; artifactKey: string }) {
  const src = jobArtifactUrl(jobId, artifactKey);
  const [failed, setFailed] = useState(false);
  return (
    <div className="flex justify-start">
      <div className="max-w-[85%] min-w-0 overflow-hidden rounded-lg border border-border bg-surface">
        {failed ? (
          <div className="p-3 text-xs text-status-failed">Plot image failed to load.</div>
        ) : (
          <img src={src} alt="Job comparison plot" onError={() => setFailed(true)} className="block max-w-full" />
        )}
        <a
          href={src}
          download
          className="flex items-center gap-1.5 border-t border-border px-3 py-1.5 text-xs text-text-muted hover:text-text"
        >
          <Download size={12} />
          Download plot
        </a>
      </div>
    </div>
  );
}

export function ToolResultChip({ message }: { message: ChatMessage }) {
  const [open, setOpen] = useState(false);

  const paperBlocks = message.name === SCHOLAR_TOOL_NAME ? splitPaperBlocks(message.content) : null;
  const plotArtifact = PLOT_TOOL_NAMES.has(message.name ?? "") ? parsePlotArtifact(message.content) : null;
  const displayContent = plotArtifact ? plotArtifact.text : message.content;

  return (
    <>
      {plotArtifact && <PlotArtifactCard jobId={plotArtifact.jobId} artifactKey={plotArtifact.artifactKey} />}
      <div className="flex justify-start">
        <div className="max-w-[85%] min-w-0 rounded-lg border border-border bg-surface text-xs">
          <button
            onClick={() => setOpen((o) => !o)}
            className="flex w-full items-center gap-1.5 px-3 py-1.5 text-left text-text-muted hover:text-text"
          >
            {open ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
            <Wrench size={12} />
            <span className="font-mono">{message.name ?? "tool"}</span>
            {paperBlocks && <span className="text-[10px]">({paperBlocks.length} papers)</span>}
          </button>
          {open &&
            (paperBlocks ? (
              <div className="flex max-h-80 flex-col gap-1.5 overflow-y-auto border-t border-border p-2">
                {paperBlocks.map((block, i) => (
                  <PaperCard key={i} block={block} />
                ))}
              </div>
            ) : (
              <div className="max-h-64 overflow-y-auto overflow-x-auto border-t border-border px-3 py-2 font-mono text-[11.5px] whitespace-pre-wrap break-words text-text-muted">
                {displayContent.slice(0, 4000)}
              </div>
            ))}
        </div>
      </div>
    </>
  );
}

// A failed job says so in the conversation and stops. This is that
// statement, plus the only thing that starts an investigation: nothing
// reads the engine's output, consults a manual or proposes a corrected job
// until someone presses this button. That is the whole of what replaced
// auto-retry -- see docs/ARCHITECTURE.md's failure-flow section for why
// guessing at a fix unasked was the wrong default when a single run here
// can be hours of someone's compute.
export function FailedJobNotice({ message }: { message: ChatMessage }) {
  const notice = message.notice;
  const threadId = useChatStore((s) => s.threadId);
  const [busy, setBusy] = useState(false);
  const [started, setStarted] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!notice) return null;

  const onTroubleshoot = async () => {
    if (!threadId) return;
    setBusy(true);
    setError(null);
    try {
      await troubleshootJob(threadId, notice.job_id);
      // The turn's own messages arrive over SSE like any other turn; all
      // this has to do is stop offering the button a second time.
      setStarted(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not start troubleshooting.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex justify-start">
      <div className="max-w-[85%] min-w-0 rounded-lg rounded-bl-sm border border-status-failed/40 bg-status-failed/10 px-3.5 py-2.5 text-sm text-text">
        <div className="mb-1.5 flex items-center gap-1.5 text-xs font-medium uppercase tracking-wide text-status-failed">
          <AlertTriangle className="h-3.5 w-3.5" aria-hidden="true" />
          Job failed
        </div>
        <div className="whitespace-pre-wrap break-words">{message.content}</div>
        {notice.action === "troubleshoot" && !started && (
          <button
            type="button"
            onClick={onTroubleshoot}
            disabled={busy || !threadId}
            className="mt-2.5 inline-flex items-center gap-1.5 rounded border border-border bg-surface px-2.5 py-1 text-xs font-medium text-text hover:bg-surface-raised disabled:opacity-50"
          >
            <Wrench className="h-3.5 w-3.5" aria-hidden="true" />
            {busy ? "Starting…" : "Troubleshoot"}
          </button>
        )}
        {started && (
          <div className="mt-2 text-xs text-text-muted">
            Looking at the engine's output…
          </div>
        )}
        {error && <div className="mt-2 text-xs text-status-failed">{error}</div>}
      </div>
    </div>
  );
}

export function MessageBubbleRow({ message }: { message: ChatMessage }) {
  // Checked before the AIMessage branch: a notice IS an AIMessage (written
  // by append_notice, not by the model), so the generic assistant bubble
  // would otherwise swallow it and the Troubleshoot button would never
  // render.
  if (message.notice?.kind === "job_failed") return <FailedJobNotice message={message} />;
  if (message.type === "HumanMessage") return <HumanBubble content={message.content} />;
  if (message.type === "ToolMessage") return <ToolResultChip message={message} />;
  if (message.type === "AIMessage") return <AssistantBubble content={message.content} />;
  return null;
}

import { useState } from "react";
import { ChevronDown, ChevronRight, Download, Wrench } from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { ChatMessage } from "../lib/api";
import { jobArtifactUrl } from "../lib/api";
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
const PLOT_TOOL_NAME = "plot_job_comparison";
const PLOT_ARTIFACT_RE = /^PLOT_ARTIFACT job_id=(\S+) key=(\S+)\n([\s\S]*)$/;

function parsePlotArtifact(content: string): { jobId: string; artifactKey: string; text: string } | null {
  const m = PLOT_ARTIFACT_RE.exec(content);
  return m ? { jobId: m[1], artifactKey: m[2], text: m[3] } : null;
}

export function HumanBubble({ content }: { content: string }) {
  return (
    <div className="flex justify-end">
      <div className="max-w-[80%] rounded-lg rounded-br-sm bg-accent px-3.5 py-2 text-sm text-white whitespace-pre-wrap">
        {content}
      </div>
    </div>
  );
}

export function AssistantBubble({ content, streaming }: { content: string; streaming?: boolean }) {
  if (!content) return null;
  return (
    <div className="flex justify-start">
      <div className="max-w-[85%] rounded-lg rounded-bl-sm bg-surface px-3.5 py-2 text-sm text-text prose-invert [&_p]:my-1.5 [&_ul]:my-1.5 [&_ol]:my-1.5 [&_pre]:my-2 [&_pre]:overflow-x-auto [&_pre]:rounded [&_pre]:bg-bg [&_pre]:p-2 [&_code]:font-mono [&_code]:text-[12.5px]">
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
      <div className="max-w-[85%] overflow-hidden rounded-lg border border-border bg-surface">
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
  const plotArtifact = message.name === PLOT_TOOL_NAME ? parsePlotArtifact(message.content) : null;
  const displayContent = plotArtifact ? plotArtifact.text : message.content;

  return (
    <>
      {plotArtifact && <PlotArtifactCard jobId={plotArtifact.jobId} artifactKey={plotArtifact.artifactKey} />}
      <div className="flex justify-start">
        <div className="max-w-[85%] rounded-lg border border-border bg-surface text-xs">
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
              <div className="max-h-64 overflow-y-auto whitespace-pre-wrap border-t border-border px-3 py-2 font-mono text-[11.5px] text-text-muted">
                {displayContent.slice(0, 4000)}
              </div>
            ))}
        </div>
      </div>
    </>
  );
}

export function MessageBubbleRow({ message }: { message: ChatMessage }) {
  if (message.type === "HumanMessage") return <HumanBubble content={message.content} />;
  if (message.type === "ToolMessage") return <ToolResultChip message={message} />;
  if (message.type === "AIMessage") return <AssistantBubble content={message.content} />;
  return null;
}

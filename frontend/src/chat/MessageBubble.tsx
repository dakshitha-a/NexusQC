import { useState } from "react";
import { ChevronDown, ChevronRight, Wrench } from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { ChatMessage } from "../lib/api";
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

export function HumanBubble({ content }: { content: string }) {
  return (
    <div className="flex justify-end">
      <div className="max-w-[80%] rounded-lg rounded-br-sm bg-accent px-3.5 py-2 text-sm text-white whitespace-pre-wrap">
        {content}
      </div>
    </div>
  );
}

export function AssistantBubble({ content }: { content: string }) {
  if (!content) return null;
  return (
    <div className="flex justify-start">
      <div className="max-w-[85%] rounded-lg rounded-bl-sm bg-surface px-3.5 py-2 text-sm text-text prose-invert [&_p]:my-1.5 [&_ul]:my-1.5 [&_ol]:my-1.5 [&_pre]:my-2 [&_pre]:overflow-x-auto [&_pre]:rounded [&_pre]:bg-bg [&_pre]:p-2 [&_code]:font-mono [&_code]:text-[12.5px]">
        <ReactMarkdown remarkPlugins={[remarkGfm]}>{content}</ReactMarkdown>
      </div>
    </div>
  );
}

export function ToolResultChip({ message }: { message: ChatMessage }) {
  const [open, setOpen] = useState(false);

  const paperBlocks = message.name === SCHOLAR_TOOL_NAME ? splitPaperBlocks(message.content) : null;

  return (
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
              {message.content.slice(0, 4000)}
            </div>
          ))}
      </div>
    </div>
  );
}

export function MessageBubbleRow({ message }: { message: ChatMessage }) {
  if (message.type === "HumanMessage") return <HumanBubble content={message.content} />;
  if (message.type === "ToolMessage") return <ToolResultChip message={message} />;
  if (message.type === "AIMessage") return <AssistantBubble content={message.content} />;
  return null;
}

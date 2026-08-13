import { useState } from "react";
import { ChevronDown, ChevronRight, Wrench } from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { ChatMessage } from "../lib/api";

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
        </button>
        {open && (
          <div className="max-h-64 overflow-y-auto whitespace-pre-wrap border-t border-border px-3 py-2 font-mono text-[11.5px] text-text-muted">
            {message.content.slice(0, 4000)}
          </div>
        )}
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

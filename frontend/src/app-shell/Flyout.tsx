import * as Dialog from "@radix-ui/react-dialog";
import { X } from "lucide-react";
import type { ReactNode } from "react";

export function Flyout({
  open,
  onClose,
  title,
  widthClassName = "w-105",
  children,
  onEscapeKeyDown,
}: {
  open: boolean;
  onClose: () => void;
  title: ReactNode;
  widthClassName?: string;
  children: ReactNode;
  // Passed straight through to Radix's Dialog.Content -- lets a child
  // (e.g. SearchableText) intercept Escape via event.preventDefault() to
  // clear its own search box instead of closing the whole flyout. Must go
  // through this prop rather than a plain onKeyDown/stopPropagation
  // further down the tree: Radix's Escape-to-close listens at the
  // document level and only checks event.defaultPrevented, which a
  // nested React handler's stopPropagation() doesn't set.
  onEscapeKeyDown?: (event: KeyboardEvent) => void;
}) {
  return (
    <Dialog.Root open={open} onOpenChange={(o) => !o && onClose()}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-40 bg-black/50" />
        <Dialog.Content
          onEscapeKeyDown={onEscapeKeyDown}
          className={`fixed right-0 top-0 z-50 flex h-full ${widthClassName} max-w-[90vw] flex-col border-l border-border bg-surface shadow-2xl`}
        >
          <div className="flex items-center justify-between border-b border-border px-4 py-3">
            <Dialog.Title className="text-sm font-semibold text-text">{title}</Dialog.Title>
            <Dialog.Close className="rounded p-1.5 text-text-muted hover:bg-surface-raised hover:text-text">
              <X size={15} />
            </Dialog.Close>
          </div>
          <div className="flex-1 overflow-y-auto px-4 py-3 text-sm">{children}</div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

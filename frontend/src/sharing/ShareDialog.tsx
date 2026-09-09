import { useEffect, useMemo, useState } from "react";
import * as Dialog from "@radix-ui/react-dialog";
import { Loader2, Send, UserRound } from "lucide-react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import * as api from "../lib/api";
import { fuzzyRecordScore } from "../lib/fuzzy";
import { shareOutboxQueryKey } from "../lib/queries";

/**
 * Offer a job or a project to another user.
 *
 * The wording throughout says "send a copy", because that is literally what
 * happens and the distinction matters to the person clicking. The recipient
 * gets their own copy under their own id, so it survives the sender later
 * deleting theirs -- and equally, the sender's later edits and renames do
 * NOT reach it. Neither half of that is obvious from a button labelled
 * "Share", so the dialog says it rather than leaving it to be discovered.
 *
 * Nothing is copied here. This creates a pending offer; the bytes move only
 * if the recipient accepts, which is what stops anyone pushing gigabytes
 * into somebody else's quota and what makes withdrawing possible.
 *
 * Structure follows projects/ProjectDeleteDialog.tsx -- a centred Radix
 * dialog whose parent owns nothing and which holds its own mutation --
 * except for that component's onOpenAutoFocus override. There, focus is
 * deliberately taken away from the buttons so no answer happens by reflex.
 * Here the first thing the user wants is the search box, so Radix's default
 * "focus the first focusable child" is exactly right and is left alone.
 */
export function ShareDialog({
  kind, resourceId, resourceName, open, onClose,
}: {
  kind: "job" | "project";
  resourceId: string;
  resourceName: string;
  open: boolean;
  onClose: () => void;
}) {
  const [query, setQuery] = useState("");
  const [picked, setPicked] = useState<api.UserSearchRow | null>(null);
  const [note, setNote] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [sentTo, setSentTo] = useState<string | null>(null);
  const queryClient = useQueryClient();

  useEffect(() => {
    if (!open) {
      setQuery("");
      setPicked(null);
      setNote("");
      setError(null);
      setSentTo(null);
    }
  }, [open]);

  // The server already prefix-matches and caps the result set; it needs two
  // characters before it will answer at all, so asking sooner would only
  // ever return []. `enabled` keeps that from being a request per keystroke
  // on the first letter.
  const trimmed = query.trim();
  const usersQuery = useQuery({
    queryKey: ["user-search", trimmed],
    queryFn: () => api.searchUsers(trimmed),
    enabled: open && trimmed.length >= 2,
  });

  // Re-ranked client-side on top of the server's ordering, so the person
  // you meant floats up when the query matches a name rather than the
  // start of a handle. Username and the two name fields carry equal weight
  // -- unlike JobManagerPanel's row scoring there is no opaque id here that
  // needs holding down.
  const results = useMemo(() => {
    const rows = usersQuery.data ?? [];
    if (!trimmed) return rows;
    return rows
      .map((u) => ({
        u,
        score: fuzzyRecordScore(
          [
            { text: u.username, weight: 1 },
            { text: u.first_name, weight: 1 },
            { text: u.last_name, weight: 1 },
          ],
          trimmed,
        ),
      }))
      .filter((r) => r.score !== null)
      .sort((a, b) => (b.score as number) - (a.score as number))
      .map((r) => r.u);
  }, [usersQuery.data, trimmed]);

  const sendMutation = useMutation({
    mutationFn: () => api.createShare(kind, resourceId, picked!.id, note.trim()),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: shareOutboxQueryKey });
      setSentTo(picked?.username ?? null);
    },
    onError: (e) => setError(String(e instanceof Error ? e.message : e)),
  });

  const displayName = (u: api.UserSearchRow) => {
    const full = `${u.first_name} ${u.last_name}`.trim();
    return full || u.username;
  };

  return (
    <Dialog.Root open={open} onOpenChange={(o) => !o && onClose()}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-40 bg-black/50 data-[state=open]:animate-fade-in" />
        <Dialog.Content
          data-testid="share-dialog"
          className="fixed left-1/2 top-1/2 z-50 w-[26rem] max-w-[92vw] -translate-x-1/2 -translate-y-1/2 rounded-lg border border-border bg-surface p-4 shadow-2xl"
        >
          <Dialog.Title className="text-sm font-semibold text-text">
            Send a copy of &ldquo;{resourceName}&rdquo;
          </Dialog.Title>
          <Dialog.Description className="mt-1 text-xs text-text-muted">
            {sentTo
              ? `Offered to ${sentTo}. Nothing has been copied yet: it lands in their account only if they accept, and you can take the offer back until then.`
              : kind === "project"
                ? "They get their own copy of this project and every job in it. It stays theirs even if you delete yours, and your later changes will not reach it."
                : "They get their own copy of this job. It stays theirs even if you delete yours, and your later changes will not reach it."}
          </Dialog.Description>

          {sentTo ? (
            <button
              onClick={onClose}
              data-testid="share-dialog-done"
              className="mt-4 w-full rounded bg-accent px-3 py-1.5 text-xs text-on-accent"
            >
              Done
            </button>
          ) : (
            <>
              <input
                autoFocus
                value={query}
                onChange={(e) => {
                  setQuery(e.target.value);
                  setPicked(null);
                  setError(null);
                }}
                placeholder="Find someone by name or username..."
                aria-label="Find a person to send this to"
                data-testid="share-user-search"
                className="mt-3 w-full rounded border border-border bg-surface px-2 py-1.5 text-xs text-text outline-none placeholder:text-text-muted focus:border-accent"
              />

              <div className="mt-1.5 flex max-h-40 flex-col overflow-y-auto">
                {trimmed.length < 2 && (
                  <div className="px-1.5 py-1 text-2xs text-text-muted">
                    Type at least two characters.
                  </div>
                )}
                {trimmed.length >= 2 && usersQuery.isPending && (
                  <div className="px-1.5 py-1 text-2xs text-text-muted">Searching...</div>
                )}
                {trimmed.length >= 2 && !usersQuery.isPending && results.length === 0 && (
                  <div data-testid="share-user-none" className="px-1.5 py-1 text-2xs text-text-muted">
                    Nobody matches that.
                  </div>
                )}
                {results.map((u) => (
                  <button
                    key={u.id}
                    onClick={() => setPicked(u)}
                    data-testid={`share-user-${u.username}`}
                    aria-pressed={picked?.id === u.id}
                    className={`flex items-center gap-1.5 rounded px-1.5 py-1 text-left text-xs hover:bg-surface-raised ${
                      picked?.id === u.id ? "bg-accent-muted text-text" : "text-text"
                    }`}
                  >
                    <UserRound size={11} className="shrink-0 text-text-muted" />
                    <span className="fade-edge-right min-w-0 flex-1">{displayName(u)}</span>
                    <span className="shrink-0 text-3xs text-text-muted">{u.username}</span>
                  </button>
                ))}
              </div>

              <input
                value={note}
                onChange={(e) => setNote(e.target.value)}
                placeholder="Add a note (optional)"
                aria-label="Note to send with this"
                data-testid="share-note"
                className="mt-2 w-full rounded border border-border bg-surface px-2 py-1.5 text-xs text-text outline-none placeholder:text-text-muted focus:border-accent"
              />

              {error && (
                <div data-testid="share-dialog-error" className="mt-2 text-2xs text-status-failed">
                  {error}
                </div>
              )}

              <div className="mt-3 flex items-center justify-end gap-2">
                <button
                  onClick={onClose}
                  data-testid="share-dialog-cancel"
                  className="rounded px-2 py-1 text-xs text-text-muted hover:text-text"
                >
                  Cancel
                </button>
                <button
                  onClick={() => picked && sendMutation.mutate()}
                  disabled={!picked || sendMutation.isPending}
                  data-testid="share-dialog-send"
                  className="flex items-center gap-1 rounded bg-accent px-3 py-1.5 text-xs text-on-accent disabled:opacity-40"
                >
                  {sendMutation.isPending ? (
                    <Loader2 size={11} className="animate-spin" />
                  ) : (
                    <Send size={11} />
                  )}
                  Send
                </button>
              </div>
            </>
          )}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}


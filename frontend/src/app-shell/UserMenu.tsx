import * as Popover from "@radix-ui/react-popover";
import { LogOut, Settings, ShieldCheck, UserCog } from "lucide-react";
import { useState } from "react";
import { AdminPanel } from "../admin/AdminPanel";
import { AccountFlyout } from "../account/AccountFlyout";
import { useAuth } from "../auth/AuthContext";

/**
 * Account settings, the admin console and log out, behind one cogwheel in the
 * sidebar header beside the help button.
 *
 * ## What this replaced
 *
 * A full-width strip across the top of the shell holding the username and
 * three text buttons. It cost a row of vertical height on every screen, for
 * three controls that are used a handful of times a session.
 *
 * The strip itself was the fix for F-013, where these controls had been an
 * absolutely-positioned overlay in the shell's top-right corner -- which is
 * exactly where RightDock puts its own collapse toggle in BOTH of its states,
 * so a click aimed at a layout toggle landed on "Log out". That hazard is
 * specific to that corner. Anchoring to the sidebar header instead is clear of
 * RightDock entirely, at every viewport width, and Radix Popover positions the
 * panel against the trigger rather than against the viewport.
 *
 * ## Three things that are load-bearing
 *
 * - **The username is a plain span, not a button.** Making it a trigger was
 *   tried once and reverted: Playwright's `has-text` is a case-insensitive
 *   SUBSTRING match, so `button:has-text("Admin")` -- how several specs locate
 *   the admin console -- started matching the username button of any account
 *   called something like `qatest_admin`. For the same reason no label here
 *   may contain "Admin" as a substring of something else.
 * - **Every item carries a testid**, so specs never have to go through
 *   `has-text` and re-open that trap.
 * - **Renders nothing when there is no user.** On a no-auth local-dev
 *   deployment the auth router is never mounted at all, so an Account item
 *   would open a flyout whose every request 404s. The old AccountBar opened
 *   with the same guard; it has to move here with the controls.
 */
export function UserMenu({ compact = false }: { compact?: boolean }) {
  const { user, logout } = useAuth();
  const [open, setOpen] = useState(false);
  const [adminOpen, setAdminOpen] = useState(false);
  const [accountOpen, setAccountOpen] = useState(false);

  if (!user) return null;

  const item =
    "flex w-full items-center gap-2 rounded px-2 py-1.5 text-left text-xs text-text-muted hover:bg-surface-raised hover:text-text";

  return (
    <>
      <Popover.Root open={open} onOpenChange={setOpen}>
        <Popover.Trigger asChild>
          <button
            data-testid="user-menu-open"
            title="Account, settings and sign out"
            aria-label="Account, settings and sign out"
            className={`rounded text-text-muted hover:bg-surface-raised hover:text-text ${compact ? "p-2" : "p-1.5"}`}
          >
            <Settings size={compact ? 16 : 15} />
          </button>
        </Popover.Trigger>
        <Popover.Portal>
          <Popover.Content
            side="bottom"
            align="start"
            sideOffset={6}
            data-testid="user-menu"
            className="z-50 w-52 rounded-md border border-border bg-surface p-1 shadow-2xl data-[state=open]:animate-fade-in"
          >
            <div className="border-b border-border px-2 pb-1.5 pt-1">
              <div className="truncate text-xs text-text" title={user.username}>
                {user.username}
              </div>
              <div className="truncate text-[11px] text-text-muted" title={user.email}>
                {user.email}
              </div>
            </div>
            <div className="pt-1">
              <button
                onClick={() => {
                  setOpen(false);
                  setAccountOpen(true);
                }}
                data-testid="account-open"
                className={item}
              >
                <UserCog size={13} /> Account settings
              </button>
              {user.role === "admin" && (
                <button
                  onClick={() => {
                    setOpen(false);
                    setAdminOpen(true);
                  }}
                  data-testid="admin-open"
                  className={item}
                >
                  <ShieldCheck size={13} /> Admin console
                </button>
              )}
              <button
                onClick={() => {
                  setOpen(false);
                  logout();
                }}
                data-testid="shell-logout"
                className={item}
              >
                <LogOut size={13} /> Log out
              </button>
            </div>
          </Popover.Content>
        </Popover.Portal>
      </Popover.Root>
      {adminOpen && <AdminPanel onClose={() => setAdminOpen(false)} />}
      <AccountFlyout open={accountOpen} onClose={() => setAccountOpen(false)} />
    </>
  );
}

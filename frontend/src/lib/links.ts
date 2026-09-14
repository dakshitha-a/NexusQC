// The links the admin console hands out, and the address they are built on.
//
// A link has to work for the person it is given to, not for the admin who
// copied it. Building it from `window.location.origin` was right as long as
// everyone reached the deployment at one address, and wrong the day the host
// was a Tailscale node SHARED with each user rather than joined to one
// tailnet: every recipient reaches it at their own address, and a link
// carrying the admin's is dead for all of them. So the base comes from the
// deployment's configured public address when there is one (the tailnet's
// MagicDNS name, which Tailscale resolves inside each recipient's tailnet),
// and only falls back to the browser's origin when nothing is configured,
// which is exactly the old behaviour for the deployments where it was fine.
//
// The shape is the deep-link contract LoginScreen.tsx parses: a bare
// ?invite= or ?reset= query on the root. There is no router in this app.
import type { AdminConfig } from "./api";

export function deploymentOrigin(config: AdminConfig | undefined): string {
  return config?.public_url || window.location.origin;
}

export function inviteLink(token: string, origin: string): string {
  return `${origin}/?invite=${token}`;
}

export function resetLink(token: string, origin: string): string {
  return `${origin}/?reset=${token}`;
}

/** What the console says next to the address about where it came from. */
export function publicUrlSourceLabel(source: AdminConfig["public_url_source"] | undefined): string {
  switch (source) {
    case "setting":
      return "set here, in the console";
    case "env":
      return "from QC_AGENT_PUBLIC_URL in .env";
    default:
      return "not set; links use each admin's own browser address";
  }
}

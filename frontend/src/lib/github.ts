// Links from the app into the public repository's issue tracker.
//
// Nothing here posts anything: every function returns a URL the browser opens
// in a new tab, where GitHub's own issue form takes over with some fields
// already filled in. The user sees exactly what will be filed and files it
// themselves, under their own account.
//
// The query-string keys are the `id`s of the text fields in
// .github/ISSUE_TEMPLATE/bug_report.yml and feature_request.yml; GitHub
// prefills a form field from a parameter of the same name. Only text fields
// (input, textarea) can be prefilled that way, which is why the version is an
// input on the form and not a dropdown. Rename an id in the form and rename
// it here, or the prefill silently lands nowhere.

export const PUBLIC_REPO_URL = "https://github.com/dakshitha-a/NexusQC";

// GitHub rejects a request whose URL is too long, and a full-length in-app
// report (up to a thousand words) URL-encodes past that. A report this long
// keeps its head and says where the rest is.
const MAX_DESCRIPTION_CHARS = 3500;
const TRUNCATION_NOTE = "\n\n(truncated; the full text is in the deployment's bug inbox)";

function clipDescription(text: string): string {
  if (text.length <= MAX_DESCRIPTION_CHARS) return text;
  return text.slice(0, MAX_DESCRIPTION_CHARS - TRUNCATION_NOTE.length) + TRUNCATION_NOTE;
}

/** "v1.1.0 (0123456789ab)", or "unknown" when neither is stamped. Shown in
 *  Help -> About and written into the bug form's version field. */
export function versionLabel(version: string, commit: string): string {
  const short = commit === "unknown" ? "unknown" : commit.slice(0, 12);
  if (version === "unknown" && short === "unknown") return "unknown";
  if (version === "unknown") return short;
  return `${version} (${short})`;
}

export function bugReportUrl(opts: { version: string; commit: string; description?: string }): string {
  const params = new URLSearchParams({
    template: "bug_report.yml",
    version: versionLabel(opts.version, opts.commit),
  });
  if (opts.description && opts.description.trim()) {
    params.set("description", clipDescription(opts.description.trim()));
  }
  return `${PUBLIC_REPO_URL}/issues/new?${params.toString()}`;
}

export function featureRequestUrl(opts: { version: string; commit: string }): string {
  const params = new URLSearchParams({
    template: "feature_request.yml",
    version: versionLabel(opts.version, opts.commit),
  });
  return `${PUBLIC_REPO_URL}/issues/new?${params.toString()}`;
}

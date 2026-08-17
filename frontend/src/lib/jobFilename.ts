// Filenames for everything the app hands a user, named after the job rather
// than its id.
//
// THIS IS THE SECOND COPY. The authoritative one is job_filename_stem() in
// app/chemistry/jobs/naming.py, which names the downloads the SERVER sends
// (the whole-job zip and PySCF's text report, via Content-Disposition). This
// copy names the ones the BROWSER builds -- blob downloads, canvas captures,
// and text the flyouts already hold in memory.
//
// The two must agree, because the same job's files land in the same folder
// whichever route produced them. If you change one, change the other, and check
// them against each other -- a drift here is invisible to a browser test, since
// the two names appear in different places.
import type { JobRow } from "./api";

// Case is deliberately preserved: "water_HF_sto-3g_PYSCF" reads better than
// "water_hf_sto-3g_pyscf", and the acronyms are how chemists write them.
// Everything outside [A-Za-z0-9._-] becomes an underscore, which handles both
// the separators auto_job_name produces and the quotes/newlines a free-text job
// label could otherwise smuggle into a filename.
export function slugifyLabel(label: string, maxLen = 80): string {
  const replaced = Array.from(label ?? "")
    .map((ch) => (/[A-Za-z0-9._-]/.test(ch) ? ch : "_"))
    .join("");
  const collapsed = replaced.replace(/_+/g, "_").replace(/^[._-]+|[._-]+$/g, "");
  return collapsed.slice(0, maxLen).replace(/[._-]+$/g, "");
}

// `{YYYYMMDD}_{slugified label}_{short id}`.
//
// The date is UTC, matching the Python side. Local time here against UTC there
// would give one job two different names on either side of midnight.
//
// The short id is what keeps this unique: job labels are not. Running the same
// calculation twice produces two jobs with identical labels, and without a
// discriminator the browser silently appends "(1)" and nobody can tell which
// file came from which job.
export function jobFilenameStem(job: Pick<JobRow, "job_id" | "label" | "created_at">): string {
  const parts: string[] = [];
  if (job.created_at) {
    const d = new Date(job.created_at * 1000);
    if (!Number.isNaN(d.getTime())) {
      const iso = d.toISOString(); // always UTC
      parts.push(`${iso.slice(0, 4)}${iso.slice(5, 7)}${iso.slice(8, 10)}`);
    }
  }
  const slug = slugifyLabel(job.label ?? "");
  if (slug) parts.push(slug);
  parts.push((job.job_id ?? "").slice(0, 8));
  return parts.filter(Boolean).join("_") || "job";
}

// The literal input file each engine's binary parses, and therefore the
// extension that makes a downloaded copy open in the right editor.
// PySCF is absent on purpose: it has no input file at all and
// /api/jobs/{id}/raw_input returns 404 there (see server/routes/jobs.py's
// _ENGINE_INPUT_FILES).
const RAW_INPUT_EXT: Record<string, string> = { orca: "inp", bagel: "json" };

export function rawInputFilename(job: Pick<JobRow, "job_id" | "label" | "created_at" | "engine">): string {
  const ext = RAW_INPUT_EXT[job.engine ?? ""] ?? "txt";
  return `${jobFilenameStem(job)}_raw_input.${ext}`;
}

// Both ORCA and BAGEL write a plain text log (output.out / bagel.out).
export function rawOutputFilename(job: Pick<JobRow, "job_id" | "label" | "created_at">): string {
  return `${jobFilenameStem(job)}_raw_output.out`;
}

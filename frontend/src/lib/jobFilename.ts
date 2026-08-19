// Filenames for everything the app hands a user, named after the job rather
// than its id.
//
// The stem itself is NOT computed here. It is computed once, by
// job_filename_stem() in app/chemistry/jobs/naming.py, and served on every
// job row as `filename_stem` -- so the name the server puts in a
// Content-Disposition header and the name the browser gives a blob download
// are the same string rather than two implementations that agree by
// convention. They used to be exactly that: two copies, one per language,
// each carrying a comment asking whoever edited it to remember the other.
// A drift between them was invisible to any browser test, because the two
// names appear on different downloads.
//
// What is left here is the part that is genuinely the browser's: which
// extension to hang off that stem.
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

// The server's stem, verbatim.
//
// The local fallback is for a job row served before `filename_stem`
// existed -- it produces the same shape, and a download named from it is
// still unique because the short id is on the end.
export function jobFilenameStem(
  job: Pick<JobRow, "job_id" | "label" | "created_at"> & { filename_stem?: string },
): string {
  if (job.filename_stem) return job.filename_stem;

  const parts: string[] = [];
  if (job.created_at) {
    const d = new Date(job.created_at * 1000);
    if (!Number.isNaN(d.getTime())) {
      const iso = d.toISOString(); // always UTC, matching the Python side
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

import type { JobRow } from "../lib/api";

/**
 * The engine a job ran on, in its own hue.
 *
 * Which program produced a number is the first thing a chemist wants from a
 * job row, and it was rendered as grey monospace text after the job id, which
 * is the least readable thing on the row. A stable colour per engine means it
 * can be picked out without being read, and the three hues are the ones the
 * README's own badges already use.
 *
 * Unknown engines fall back to muted text rather than being dropped: a blind
 * input file can name something this app has no colour for, and silently
 * hiding it would be worse than showing it plainly.
 */
const HUE: Record<string, string> = {
  pyscf: "text-engine-pyscf",
  orca: "text-engine-orca",
  bagel: "text-engine-bagel",
};

export function EngineTag({ engine }: { engine: JobRow["engine"] }) {
  if (!engine) return null;
  return <span className={`font-medium ${HUE[engine] ?? "text-text-muted"}`}>{engine}</span>;
}

/** The colour a row should flash when it reaches this state, as a value for
 *  --flash-color. The flash used to be the accent whatever had happened, so a
 *  job that failed and a job that finished looked identical for the 900ms that
 *  was the only notification either of them got. */
export function flashColor(status: JobRow["status"]): string {
  return `color-mix(in srgb, var(--status-${status}) 22%, transparent)`;
}

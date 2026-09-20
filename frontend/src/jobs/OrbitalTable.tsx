import { useEffect, useRef } from "react";
import { ROW_FOCUS_CLASS, rowProps } from "../lib/rowProps";

// Shows the per-orbital energy/occupancy table any engine's mo_visualization
// job produces in summary.orbital_table (same {index, spin, energy_eV,
// occupancy} shape from pyscf_runner, orca_runner, and app.chemistry.jobs.molden
// -- see CLAUDE.md's Phase 4 note). Rows are click-selectable, driving
// MoCubeViewer's lazy per-orbital cube fetch via POST
// /api/jobs/{id}/orbitals/{index}/cube.
export interface OrbitalRow {
  index: number;
  spin: string | null;
  energy_eV: number;
  occupancy: number;
  // Only populated by recommend_active_space today (see
  // classify_orbital_character in pyscf_runner.py) -- character is
  // "sigma"/"pi"/"n"/"sigma*"/"pi*"/null (unclassified), localized_atom is
  // a short label like "O1" or "C1-C2", or "delocalized over ..." for an
  // orbital that isn't cleanly localized on 1-2 atoms.
  character?: string | null;
  localized_atom?: string | null;
  // Fraction of the orbital's density lying outside 1.5 van der Waals radii
  // of every atom, and the flag derived from it at 0.5 (see
  // _diffuse_fractions in app/chemistry/jobs/molden.py). Populated by the
  // PySCF and BAGEL paths; ORCA tables carry neither this nor character.
  // The fraction is shown rather than just the flag, so an orbital at 0.42
  // stays visible instead of being rounded away into "not diffuse".
  diffuse_fraction?: number | null;
  diffuse?: boolean;
  // The active-space record (app/chemistry/jobs/active_space.py). `active`
  // is on every row of a CASSCF-family table: the rows of the active window.
  // The two reference fields are on active rows when the run could be
  // compared with the orbitals it started from: the reference-table row
  // this orbital most resembles and the squared overlap with it.
  active?: boolean;
  reference_index?: number;
  reference_weight?: number;
}

export interface OrbitalSelection {
  index: number;
  spin: string | null;
  // ORCA-only: renders from a specific .gbw file other than the job's own
  // input.gbw (e.g. "input_im3.gbw") -- used by NebFrameViewer to render
  // orbitals from a specific path image's own wavefunction. Omitted for
  // every other caller (OrbitalTable's own rows), which always render from
  // input.gbw.
  gbw?: string;
}

interface Props {
  rows: OrbitalRow[];
  selected?: OrbitalSelection | null;
  onSelect: (row: OrbitalRow) => void;
  /** Grow the scroll box to whatever height the parent gives it, instead of
   * the short fixed box used when the table sits above the viewer. Set when
   * the enclosing panel is expanded and the table is a full-height column
   * beside the viewer. */
  fill?: boolean;
  /** One line about the active window, composed by the drawer from the
   * summary ("Active space: rows 24 to 32, named against job faee12's
   * table"). Shown in the header line beside the orbital count. */
  activeSpaceNote?: string | null;
  /** The summary's active_space_warning: the optimizer did not keep the
   * space it started from. Shown in the accent colour above the table, since
   * it changes what every number below it means. */
  warning?: string | null;
}

/** Unoccupied orbitals shown per spin channel before the rest are pruned.
 * Table order already runs low-to-high energy per channel (see
 * pyscf_runner.py/orca_runner.py's orbital_table construction), so "first
 * N" is exactly "the N lowest-energy virtuals" -- the HOMO/LUMO region
 * anyone actually inspects, not an arbitrary cutoff. */
export const MAX_UNOCCUPIED_SHOWN = 20;

/** Keeps every occupied row, and up to MAX_UNOCCUPIED_SHOWN unoccupied rows
 * per spin channel (an unrestricted job's alpha/beta rows are independent
 * index sequences -- see OrbitalRow's doc comment above -- so pruning has to
 * count separately per channel or it would silently drop one spin's virtuals
 * entirely once the other spin's had used up the budget). Exported so
 * JobDetailDrawer's orbital scrubber can navigate exactly the rows this
 * table renders, rather than a separately-derived list that could disagree. */
export function pruneOrbitalRows(rows: OrbitalRow[]): { shown: OrbitalRow[]; hiddenCount: number } {
  const unoccupiedSeenPerSpin = new Map<string, number>();
  const shown: OrbitalRow[] = [];
  let hiddenCount = 0;
  for (const r of rows) {
    if (r.occupancy > 0) {
      shown.push(r);
      continue;
    }
    const key = r.spin ?? "_";
    const seen = unoccupiedSeenPerSpin.get(key) ?? 0;
    if (seen < MAX_UNOCCUPIED_SHOWN) {
      shown.push(r);
      unoccupiedSeenPerSpin.set(key, seen + 1);
    } else {
      hiddenCount++;
    }
  }
  return { shown, hiddenCount };
}

export function OrbitalTable({ rows, selected, onSelect, fill, activeSpaceNote, warning }: Props) {
  const { shown, hiddenCount } = pruneOrbitalRows(rows);
  const hasSpin = shown.some((r) => r.spin);
  const hasCharacter = shown.some((r) => r.character || r.localized_atom);
  const hasDiffuse = shown.some((r) => typeof r.diffuse_fraction === "number");
  const hasActive = shown.some((r) => r.active);
  const hasReference = shown.some((r) => typeof r.reference_index === "number");
  const selectedRowRef = useRef<HTMLTableRowElement>(null);

  // The scrubber beside this table can move the selection to a row that is
  // scrolled out of sight -- and a table that goes on showing a different
  // highlighted row than the viewer is rendering is worse than no highlight at
  // all. "nearest" scrolls only when the row is actually off-screen, so
  // clicking a visible row never yanks the list around under the cursor.
  useEffect(() => {
    selectedRowRef.current?.scrollIntoView({ block: "nearest" });
  }, [selected?.index, selected?.spin]);

  return (
    <div className={`flex min-h-0 flex-col gap-1 ${fill ? "h-full" : ""}`}>
      <div className="text-3xs text-text-muted">
        {rows.length} orbital{rows.length === 1 ? "" : "s"} total
        {hiddenCount > 0 &&
          ` · ${hiddenCount} higher unoccupied orbital${hiddenCount === 1 ? "" : "s"} not shown`}
        {activeSpaceNote && <span data-testid="orbital-active-note">{` · ${activeSpaceNote}`}</span>}
      </div>
      {warning && (
        // The one thing on this panel that must be read before the numbers:
        // the energies belong to a different active space than the one that
        // was asked for. Accent rather than a status colour, because it is
        // not a failure; the job ran, and this is what it found.
        <div className="text-3xs text-accent" data-testid="orbital-active-warning">
          {warning}
        </div>
      )}
      <div
        className={`overflow-y-auto rounded border border-border ${
          fill ? "min-h-0 flex-1" : "max-h-56"
        }`}
      >
        <table className="w-full text-xs">
          <thead className="sticky top-0 bg-surface">
            <tr className="text-left text-text-muted">
              <th className="py-1 pl-2 pr-3 font-normal">#</th>
              {hasSpin && <th className="py-1 pr-3 font-normal">Spin</th>}
              <th className="py-1 pr-3 font-normal">Energy (eV)</th>
              <th className="py-1 pr-2 font-normal">Occ.</th>
              {hasCharacter && <th className="py-1 pr-3 font-normal">Character</th>}
              {hasDiffuse && (
                <th className="py-1 pr-3 font-normal" title="Fraction of the orbital's density outside the molecule">
                  Diffuse
                </th>
              )}
              {hasCharacter && <th className="py-1 pr-2 font-normal">Localized on</th>}
              {hasReference && (
                <th className="py-1 pr-2 font-normal whitespace-nowrap" title="The orbital this run started from, and how much of it survives in this one">
                  From
                </th>
              )}
            </tr>
          </thead>
          <tbody>
            {shown.map((r) => {
              const isSelected = selected?.index === r.index && (selected?.spin ?? null) === (r.spin ?? null);
              return (
                <tr
                  key={`${r.spin ?? ""}-${r.index}`}
                  ref={isSelected ? selectedRowRef : undefined}
                  data-testid={`orbital-row-${r.index}${r.spin ? `-${r.spin}` : ""}`}
                  onClick={() => onSelect(r)}
                  {...rowProps(() => onSelect(r), { selected: isSelected })}
                  data-active={r.active ? "true" : undefined}
                  className={`cursor-pointer border-t border-border hover:bg-surface-raised ${ROW_FOCUS_CLASS} ${
                    isSelected ? "bg-surface-raised" : ""
                  }`}
                >
                  {/* The active window carries the app's hairline, on the
                      cell rather than the row for the same reason the job
                      tables put it there (a table row is not positioned). It
                      marks state, not selection: these are the orbitals the
                      wavefunction correlates, whatever row is highlighted.
                      The header line above names the rows in words, so the
                      mark is never the only carrier; a text tag beside each
                      index was tried and cost the width the From column
                      needs in the drawer. */}
                  <td
                    className={`py-1 pl-2 pr-3 font-mono ${r.active ? "hairline text-text" : "text-text-muted"}`}
                    title={r.active && hasActive ? "In the active space" : undefined}
                  >
                    {r.index}
                  </td>
                  {hasSpin && <td className="py-1 pr-3 font-mono text-text-muted">{r.spin}</td>}
                  <td className={`py-1 pr-3 font-mono ${r.occupancy > 0 ? "text-text" : "text-text-muted"}`}>
                    {r.energy_eV?.toFixed(3) ?? "--"}
                  </td>
                  <td className="py-1 pr-2 font-mono text-text-muted">{r.occupancy?.toFixed(2) ?? "--"}</td>
                  {hasCharacter && <td className="py-1 pr-3 font-mono text-text-muted">{r.character ?? "--"}</td>}
                  {hasDiffuse && (
                    <td className={`py-1 pr-3 font-mono ${r.diffuse ? "text-accent" : "text-text-muted"}`}>
                      {typeof r.diffuse_fraction === "number" ? r.diffuse_fraction.toFixed(2) : "--"}
                    </td>
                  )}
                  {hasCharacter && <td className="py-1 pr-2 font-mono text-text-muted">{r.localized_atom ?? "--"}</td>}
                  {hasReference && (
                    <td
                      className={`py-1 pr-2 font-mono whitespace-nowrap ${
                        typeof r.reference_weight === "number" && r.reference_weight < 0.5 ? "text-accent" : "text-text-muted"
                      }`}
                    >
                      {typeof r.reference_index === "number"
                        ? `#${r.reference_index} · ${(r.reference_weight ?? 0).toFixed(2)}`
                        : "--"}
                    </td>
                  )}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

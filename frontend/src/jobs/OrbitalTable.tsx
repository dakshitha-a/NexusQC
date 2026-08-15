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
}

export function OrbitalTable({ rows, selected, onSelect }: Props) {
  const hasSpin = rows.some((r) => r.spin);
  return (
    <div className="max-h-56 overflow-y-auto rounded border border-border">
      <table className="w-full text-xs">
        <thead className="sticky top-0 bg-surface">
          <tr className="text-left text-text-muted">
            <th className="py-1 pl-2 pr-3 font-normal">#</th>
            {hasSpin && <th className="py-1 pr-3 font-normal">Spin</th>}
            <th className="py-1 pr-3 font-normal">Energy (eV)</th>
            <th className="py-1 pr-2 font-normal">Occ.</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => {
            const isSelected = selected?.index === r.index && (selected?.spin ?? null) === (r.spin ?? null);
            return (
              <tr
                key={`${r.spin ?? ""}-${r.index}`}
                onClick={() => onSelect(r)}
                className={`cursor-pointer border-t border-border hover:bg-surface-raised ${
                  isSelected ? "bg-surface-raised" : ""
                }`}
              >
                <td className="py-1 pl-2 pr-3 font-mono text-text-muted">{r.index}</td>
                {hasSpin && <td className="py-1 pr-3 font-mono text-text-muted">{r.spin}</td>}
                <td className={`py-1 pr-3 font-mono ${r.occupancy > 0 ? "text-text" : "text-text-muted"}`}>
                  {r.energy_eV.toFixed(3)}
                </td>
                <td className="py-1 pr-2 font-mono text-text-muted">{r.occupancy.toFixed(2)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

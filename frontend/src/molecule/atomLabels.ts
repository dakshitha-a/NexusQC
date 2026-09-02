// The numbered chips drawn over each atom, in one place.
//
// Three components own a 3Dmol viewer -- MoleculeViewer, MoCubeViewer and
// ModeAnimationViewer -- and each carried its own copy of this block. They
// also each cleared the labels differently (removeAllLabels in one, a
// whole-scene clear() in the other two), so the toggle needed a single
// definition of "put the labels in the state the user asked for" that does
// not care what the caller did to the scene beforehand.
import type { GLViewer } from "3dmol";

/** An atom position in the viewer's own frame, i.e. Angstrom. Deliberately
 * not MoleculeDict's [x, y, z] tuple: MoCubeViewer reads its positions back
 * out of the model 3Dmol parsed from a cube file, which is where the
 * Bohr-to-Angstrom conversion has already happened. */
export interface LabelPosition {
  x: number;
  y: number;
  z: number;
}

/** Dark chip, light text, always drawn over the geometry rather than into
 * it -- an atom number half-buried in a sphere is worse than none. */
export const ATOM_LABEL_STYLE = {
  backgroundColor: "black",
  backgroundOpacity: 0.55,
  fontColor: "white",
  fontSize: 11,
  borderThickness: 0,
  inFront: true,
  showBackground: true,
} as const;

/**
 * Put the viewer's atom labels into the requested state, whatever they were
 * in before.
 *
 * Numbering is 1-based, matching every other place a user or the model sees
 * an atom index in this app (see CLAUDE.md). The caller passes positions in
 * the model's own order, so index 0 here is atom 1 there.
 *
 * Always removes first, including when `show` is false, so this is safe to
 * call against a scene whose labels are already gone (ModeAnimationViewer
 * and MoCubeViewer both wipe theirs with `clear()` before rebuilding) and
 * against one where they are still present. It does NOT render -- the
 * caller decides when, since it usually has other scene changes to batch
 * with this one.
 */
export function applyAtomLabels(viewer: GLViewer, positions: LabelPosition[], show: boolean): void {
  viewer.removeAllLabels();
  if (!show) return;
  positions.forEach((p, i) => {
    viewer.addLabel(String(i + 1), { position: { x: p.x, y: p.y, z: p.z }, ...ATOM_LABEL_STYLE });
  });
}

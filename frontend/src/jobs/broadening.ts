// Gaussian broadening, once, for every chart in the browser that needs it.
//
// There were three implementations of this formula: one in Python
// (`app/chemistry/spectrum.py::_broadened_spectrum`) and two here, in
// `UvVisSpectrumInline.tsx` and `IrSpectrumInline.tsx`, differing only in
// their lower floor and their default width. Three copies of one formula
// drift, and the way this one would drift is quiet: an inline chart and the
// PNG rendered from the same job would disagree slightly and nothing would
// say so.
//
// Two remain rather than one, and that is deliberate rather than a shortfall.
// The client copy exists so an inline chart works on any already-completed
// job with no backend call at all -- which is the whole reason the drawer can
// show a spectrum the moment a job finishes. What was worth removing is the
// SECOND client copy, not the language boundary.
//
// Kept in step with the server by `tests/frontend/spec_02_broadening_agrees.spec.mjs`,
// which compares this against the curve the server actually rendered for the
// same job rather than against a copied constant.

/** sigma from full width at half maximum, the one line all three shared. */
export function sigmaFromFwhm(fwhm: number): number {
  return fwhm / (2 * Math.sqrt(2 * Math.log(2)));
}

export interface BroadenOptions {
  /** Points across the grid. 200 is the inline default; the server uses 2000
   *  for a rendered PNG, where the extra resolution is visible. */
  nPoints?: number;
  /** Lower bound floor. An electronic spectrum stops at 0.5 eV, since a
   *  wavelength axis divides by energy and the padding alone can otherwise
   *  reach zero; a vibrational one stops at 0 cm-1. */
  floor?: number;
  /** An explicit [lo, hi] window, which the Wigner panel's sliders supply. */
  range?: [number, number];
}

/**
 * Sum of Gaussians of equal width, one per stick, on a uniform grid.
 *
 * `positions` and `heights` are in whatever unit the caller is working in --
 * eV for an electronic spectrum, cm-1 for a vibrational one -- and `fwhm` is
 * in that same unit. The arithmetic does not care which, which is exactly why
 * one function can serve both.
 */
export function broadenedSpectrum(
  positions: number[],
  heights: number[],
  fwhm: number,
  { nPoints = 200, floor = 0, range }: BroadenOptions = {},
): { grid: number[]; y: number[] } {
  const sigma = sigmaFromFwhm(fwhm);
  const lo = range ? range[0] : Math.max(floor, Math.min(...positions) - 5 * sigma);
  const hi = range ? range[1] : Math.max(...positions) + 5 * sigma;
  const step = (hi - lo) / (nPoints - 1);
  const grid = Array.from({ length: nPoints }, (_, i) => lo + i * step);
  const y = grid.map((x) =>
    positions.reduce((acc, x0, i) => acc + heights[i] * Math.exp(-0.5 * ((x - x0) / sigma) ** 2), 0),
  );
  return { grid, y };
}

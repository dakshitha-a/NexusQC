import { useId } from "react";

/**
 * The NexusQC mark, in the three forms the app needs.
 *
 * ## What it is
 *
 * A benzene-shaped tile carrying an N drawn as a three-bond skeletal chain:
 * bond up, bond diagonally down, bond up, with an atom at each of the four
 * vertices. The hexagon is what says chemistry at a glance and the letterform
 * is what makes it ours; neither alone was enough. An earlier cut was a plain
 * rounded square with an N in it, which was perfectly legible and could have
 * belonged to any product at all, and a cut with a single node dot read as a
 * diacritic rather than as an atom.
 *
 * The gradient runs cyan to blue along the diagonal because those are two real
 * Balmer lines, H-beta at 486 nm and H-gamma at 434 nm, which is where the
 * app's whole palette is derived from. It is provenance rather than decoration,
 * which is also why it is the one gradient in the interface.
 *
 * ## Why the atoms come and go
 *
 * Below 28px the four atom circles stop reading as atoms and start reading as
 * holes punched in the letter, so they are simply not drawn. That threshold is
 * why `frontend/public/favicon.svg` is a separate hand-written file rather than
 * an export of this component: a favicon is rendered at 16px and has to be the
 * small cut permanently.
 *
 * ## Why the mark does not follow the accent
 *
 * The user can change the app's accent colour (see lib/appearanceStore.ts), and
 * the mark deliberately ignores it. A logo that changes colour with a
 * preference is not a logo. Where a control genuinely needs the shape in the
 * surrounding ink instead, use `variant="glyph"`, which draws in `currentColor`
 * and no tile.
 */

type Variant = "mark" | "glyph";

const HEX = "M32 3 58.1 18v30L32 63 5.9 48V18Z";
const CHAIN = "M18 48V17l28 31V17";
const ATOMS: [number, number][] = [
  [18, 48],
  [18, 17],
  [46, 48],
  [46, 17],
];

/** The threshold below which the atom nodes read as holes rather than atoms. */
const ATOM_MIN_PX = 28;

export function Logo({
  size = 28,
  variant = "mark",
  className,
}: {
  size?: number;
  variant?: Variant;
  className?: string;
}) {
  // Several marks can be on screen at once (the rail header and the welcome
  // screen, say), and duplicate gradient ids in one document make every
  // instance paint from whichever definition the browser resolved last.
  const gradientId = `nexusqc-mark-${useId()}`;
  const atoms = size >= ATOM_MIN_PX;

  if (variant === "glyph") {
    return (
      <svg
        viewBox="0 0 64 64"
        width={size}
        height={size}
        className={className}
        role="img"
        aria-label="NexusQC"
        data-testid="brand-logo"
      >
        <path
          d={CHAIN}
          fill="none"
          stroke="currentColor"
          strokeWidth={9}
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
    );
  }

  return (
    <svg
      viewBox="0 0 64 64"
      width={size}
      height={size}
      className={className}
      role="img"
      aria-label="NexusQC"
      data-testid="brand-logo"
    >
      <defs>
        <linearGradient id={gradientId} x1="8" y1="8" x2="56" y2="56" gradientUnits="userSpaceOnUse">
          <stop offset="0" stopColor="#34d3ea" />
          <stop offset="1" stopColor="#2f6fe0" />
        </linearGradient>
      </defs>
      {/* Stroked in its own fill so the hexagon's six corners round off; a
          bare polygon has hard points that read as jagged at small sizes. */}
      <path
        d={HEX}
        fill={`url(#${gradientId})`}
        stroke={`url(#${gradientId})`}
        strokeWidth={5}
        strokeLinejoin="round"
      />
      <path
        d={CHAIN}
        fill="none"
        stroke="#0d1117"
        strokeWidth={9}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      {atoms &&
        ATOMS.map(([cx, cy]) => <circle key={`${cx},${cy}`} cx={cx} cy={cy} r={3.7} fill="#eaf9ff" />)}
    </svg>
  );
}

/**
 * The mark beside the name, which is how the app introduces itself: the rail
 * header, the sign-in card and the welcome screen. Those three used to write
 * out "NexusQC" by hand at three different sizes, one of them beside a generic
 * flask icon, so the app had no consistent way of naming itself anywhere.
 */
export function LogoLockup({
  size = 28,
  subtitle = false,
  className,
}: {
  size?: number;
  subtitle?: boolean;
  className?: string;
}) {
  return (
    <div className={`flex min-w-0 items-center gap-2.5 ${className ?? ""}`}>
      <Logo size={size} />
      <div className="min-w-0">
        <div
          className="truncate font-semibold leading-tight text-text"
          style={{ fontSize: `${Math.round(size * 0.62)}px` }}
        >
          NexusQC
        </div>
        {subtitle && (
          <div className="truncate text-3xs leading-tight text-text-muted">
            Agentic Quantum Chemistry Engine
          </div>
        )}
      </div>
    </div>
  );
}

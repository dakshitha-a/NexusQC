import { Check, RotateCcw } from "lucide-react";
import { Flyout } from "../app-shell/Flyout";
import {
  ACCENTS,
  DENSITIES,
  FONT_SCALES,
  THEMES,
  useAppearanceStore,
  type AccentId,
  type ThemeId,
} from "../lib/appearanceStore";

/**
 * Everything about how the app looks, behind the palette button in the sidebar
 * header. The app had no preferences surface of any kind before this.
 *
 * ## The swatches are the real thing
 *
 * A theme card is not a picture of a theme. It is a div carrying
 * `data-theme` and `data-accent`, painted with the same `bg-surface` /
 * `text-text` / `bg-accent` utilities as the rest of the app, so it renders in
 * that theme's actual tokens. index.css's theme blocks are attribute-only
 * rather than `:root`-qualified precisely so this works, and `--accent-muted`
 * is restated on every themed element so a nested swatch recomputes it from
 * its own accent instead of inheriting the root's.
 *
 * That matters more than it sounds: a hand-maintained list of preview hexes is
 * a second copy of the palette, and it goes stale the first time a token is
 * adjusted without anyone noticing.
 *
 * ## Why it is not inside the cogwheel
 *
 * UserMenu renders `null` when there is no user, so on a deployment with auth
 * switched off the cogwheel does not exist at all. Appearance is not an
 * account setting and has to be reachable regardless.
 */

/** One row of choices. Kept local: nothing else in the app needs it, and the
 *  three groups differ only in what they render inside the button. */
function Choice({
  selected,
  onSelect,
  title,
  children,
  testId,
  className,
  tick = true,
}: {
  selected: boolean;
  onSelect: () => void;
  title: string;
  children: React.ReactNode;
  testId: string;
  className?: string;
  /** Off for the accent swatches: a tick in the corner of a 24px circle sits
   *  on top of the very colour being chosen. Those show selection with the
   *  border and a ring instead. */
  tick?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onSelect}
      title={title}
      aria-pressed={selected}
      data-testid={testId}
      className={`relative rounded-md border text-left transition-colors ${
        selected ? "border-accent" : "border-border hover:border-text-muted"
      } ${className ?? ""}`}
    >
      {children}
      {selected && tick && (
        <span className="absolute right-1.5 top-1.5 flex size-4 items-center justify-center rounded-full bg-accent text-on-accent">
          <Check size={10} strokeWidth={3} />
        </span>
      )}
    </button>
  );
}

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-text-muted">{children}</div>
  );
}

export function AppearanceFlyout({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { theme, accent, fontScale, density, motion } = useAppearanceStore();
  const { setTheme, setAccent, setFontScale, setDensity, setMotion, reset } = useAppearanceStore();

  return (
    <Flyout open={open} onClose={onClose} title="Appearance" widthClassName="w-96" dim={false}>
      <div className="flex flex-col gap-6 pb-4">
        <section>
          <SectionLabel>Theme</SectionLabel>
          <div className="grid grid-cols-2 gap-2">
            {THEMES.map((t) => (
              <Choice
                key={t.id}
                selected={theme === t.id}
                onSelect={() => setTheme(t.id as ThemeId)}
                title={t.blurb}
                testId={`appearance-theme-${t.id}`}
                className="overflow-hidden"
              >
                {/* The preview is that theme, not a drawing of it. */}
                <div data-theme={t.id} data-accent={accent} className="bg-bg p-2.5">
                  <div className="rounded border border-border bg-surface p-2">
                    <div className="mb-1.5 flex items-center gap-1.5">
                      <span className="size-2 rounded-full bg-accent" />
                      <span className="h-1.5 flex-1 rounded-full bg-text opacity-80" />
                    </div>
                    <div className="mb-1 h-1 w-3/4 rounded-full bg-text-muted opacity-70" />
                    <div className="flex gap-1">
                      <span className="h-1 w-4 rounded-full bg-status-running" />
                      <span className="h-1 w-4 rounded-full bg-status-completed" />
                      <span className="h-1 w-4 rounded-full bg-status-failed" />
                    </div>
                  </div>
                </div>
                <div className="border-t border-border px-2.5 py-1.5">
                  <div className="text-xs font-medium text-text">{t.name}</div>
                  <div className="text-3xs leading-snug text-text-muted">{t.blurb}</div>
                </div>
              </Choice>
            ))}
          </div>
        </section>

        <section>
          <SectionLabel>Accent</SectionLabel>
          <div className="flex flex-wrap gap-2">
            {ACCENTS.map((a) => (
              <Choice
                key={a.id}
                selected={accent === a.id}
                onSelect={() => setAccent(a.id as AccentId)}
                title={`${a.name} (${a.line})`}
                testId={`appearance-accent-${a.id}`}
                tick={false}
                className="flex flex-1 flex-col items-center gap-1.5 px-1.5 py-2"
              >
                <span
                  data-theme={theme}
                  data-accent={a.id}
                  className={`block size-6 rounded-full bg-accent ring-offset-2 ring-offset-surface ${
                    accent === a.id ? "ring-2 ring-accent" : ""
                  }`}
                />
                <span className="text-3xs font-medium text-text">{a.name}</span>
                <span className="text-3xs leading-none text-text-muted">{a.line.split(",")[1].trim()}</span>
              </Choice>
            ))}
          </div>
          <p className="mt-2 text-3xs leading-relaxed text-text-muted">
            Every accent is an emission line, and so are the status colours: a running job is sodium's
            589 nm, a finished one mercury's 546 nm, a failed one H-alpha at 656 nm.
          </p>
        </section>

        <section>
          <SectionLabel>Text size</SectionLabel>
          <div className="flex gap-1.5">
            {FONT_SCALES.map((f) => (
              <Choice
                key={f.value}
                selected={fontScale === f.value}
                onSelect={() => setFontScale(f.value)}
                title={`${Math.round(f.value * 100)}%`}
                testId={`appearance-fontscale-${String(f.value).replace(".", "")}`}
                className="flex flex-1 flex-col items-center gap-0.5 px-1 py-2"
              >
                <span className="font-semibold text-text" style={{ fontSize: `${f.value * 13}px` }}>
                  A
                </span>
                <span className="text-3xs text-text-muted">{f.label}</span>
              </Choice>
            ))}
          </div>
          <p className="mt-2 rounded-md border border-border bg-surface-raised px-2.5 py-2 text-xs leading-relaxed text-text">
            Everything scales together: this sentence, the job lists, the sidebar's width and the space
            between controls.
          </p>
        </section>

        <section>
          <SectionLabel>Density</SectionLabel>
          <div className="flex gap-1.5">
            {DENSITIES.map((d) => (
              <Choice
                key={d.id}
                selected={density === d.id}
                onSelect={() => setDensity(d.id)}
                title={d.blurb}
                testId={`appearance-density-${d.id}`}
                className="flex-1 px-2 py-2"
              >
                <div className="text-xs font-medium text-text">{d.name}</div>
                <div className="text-3xs leading-snug text-text-muted">{d.blurb}</div>
              </Choice>
            ))}
          </div>
        </section>

        <section>
          <SectionLabel>Motion</SectionLabel>
          <div className="flex gap-1.5">
            {(
              [
                ["full", "Animated", "Panels slide, rows flash when a job finishes."],
                ["reduced", "Still", "No transitions. Also on if your system asks for it."],
              ] as const
            ).map(([id, name, blurb]) => (
              <Choice
                key={id}
                selected={motion === id}
                onSelect={() => setMotion(id)}
                title={blurb}
                testId={`appearance-motion-${id}`}
                className="flex-1 px-2 py-2"
              >
                <div className="text-xs font-medium text-text">{name}</div>
                <div className="text-3xs leading-snug text-text-muted">{blurb}</div>
              </Choice>
            ))}
          </div>
        </section>

        <button
          type="button"
          onClick={reset}
          data-testid="appearance-reset"
          className="flex items-center gap-1.5 self-start rounded-md border border-border px-2.5 py-1.5 text-xs text-text-muted hover:border-text-muted hover:text-text"
        >
          <RotateCcw size={12} />
          Back to defaults
        </button>
      </div>
    </Flyout>
  );
}

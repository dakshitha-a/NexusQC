# Tracker: a brand mark, a theming system, and a critical UI pass

<!-- artifact: pending first publish -->

**In motion, opened 2026-09-09.** Seven phases. Gives NexusQC a logo it does not
currently have, rebuilds the design tokens into four switchable themes with a
user-controlled text size, and works through a list of interface defects that
range from a conversation list with no scrollbar to a `+` button that does
nothing while its drawer is closed.

It stays here rather than moving to [`trackers/`](trackers/) until the next
plan starts. **Exactly one tracker is active at a time.** The one this replaces
is
[`trackers/2026-09-one-command-install-and-in-app-update.md`](trackers/2026-09-one-command-install-and-in-app-update.md).

## Rules (enforced by `scripts/check_tracker.py`)

- Step status is exactly one of `todo` | `in-progress` | `done`.
- A step may be marked `done` **only with an evidence field**: the
  verification script/command path plus a one-line observed result.
- The tracker edit ships **in the same commit** as the step's final code
  change, so `git log --follow docs/TRACKER.md` is the audit trail.
- A phase's `merged` row records the commit hash the stage landed as, and it
  must be a bare hash; the checker rejects anything else.

Format for a step row:

```
- [status] P<phase>.<step>: <short name>
  evidence: <script/command> → "<observed result>"   (required when done)
```

---

## Why this plan exists

The app had no visual identity at all. `frontend/public/favicon.svg` was a
purple lightning glyph left over from the commit that created the frontend,
whose colour fights the app's own accent, and `frontend/public/icons.svg` was a
sprite of Bluesky, Discord and X icons that nothing referenced. The wordmark
"NexusQC" was plain text written out by hand in three places at three different
sizes, with a generic flask icon standing in for a logo in one of them.

The interface had also drifted small and rigid. Of roughly 513 font-size
utilities, 472 were 12px or below, and 227 of those were hard-coded
`text-[10px]` / `text-[10.5px]` / `text-[11px]` values that bypassed the token
system entirely, so no global change of scale was possible. There was no light
mode, no text-size control, and no appearance surface of any kind.

Four defects were reported or found by reading, and all four are structural
rather than cosmetic:

1. **The conversation list grew without bound.** It had no cap and no scroll
   container of its own, so a user with many conversations pushed the Knowledge
   base, Files, Projects and Shared-with-me drawers below the fold with no way
   back short of deleting conversations. The right dock had already solved
   exactly this with `max-h` caps and internal scroll; the left rail never got
   it.
2. **A drawer's `+` button did nothing while the drawer was collapsed.** The
   form it reveals lives inside the section body, which is unmounted while
   collapsed, and all three of those sections default to collapsed. The first
   click flipped the icon to an X and showed nothing.
3. **Permanent search bars and permanent storage readouts** spent rows in the
   panels least able to spare them. The job manager is the app's only `flex-1`
   pane, so every row above the list is jobs not shown.
4. **The right dock's collapsed strip was inert.** Four `<div>`s with tooltips:
   it told you which panels existed and reached none of them. The left rail had
   fixed this same bug for itself and left the dock behind.

Two decisions were taken with the user before any code was written. The theme
set is four themes **including a real light mode**, which is the expensive
option because the 3D viewer's background is hardcoded and CPK hydrogens render
white and would vanish on a pale field. And the colour system is **re-derived
from real spectral lines** with that as the new default, rather than preserving
the existing periwinkle accent.

---

## Phase 1: A mark that survives 16 pixels

The logo is a skeletal zig-zag, which is how a chemist draws a carbon chain,
whose stroke geometry also reads as an N, with one vertex carrying a filled
node: the nexus, the active site. Designed at favicon size first, because that
is the case that kills detailed marks.

- [done] P1.1: Draw the mark and prove it at 16, 32, 128 and 512 px
  evidence: tests/frontend/brand_sheet.mjs → "renders docs/brand-sheet.png; the hexagon silhouette and the N both read at 16px in the light and dark tab simulations, and the four atom nodes correctly stop being drawn below 28px where they had turned into holes"
- [done] P1.2: Logo.tsx with mark, glyph and lockup variants
  evidence: frontend/src/brand/Logo.tsx → "npm run build (tsc -b then vite build) passes with the component compiled in; gradient ids are per-instance via useId so two marks on one page cannot steal each other's fill"
- [done] P1.3: Replace the scaffold favicon, add theme-color, delete icons.svg
  evidence: frontend/public/favicon.svg → "the purple scaffold glyph is gone and public/ now holds only the new mark; icons.svg, a Bluesky/Discord/X sprite that grep found referenced nowhere in src, index.html or nginx, is deleted"
- [done] P1.4: README assets that render without CSS or webfonts
  evidence: docs/logo.svg → "every colour is an explicit hex and there is no text element, so GitHub, which renders SVG with no CSS context and no webfonts, shows the same mark the app does"

## Phase 2: Tokens, type scale, and the appearance store

The foundation every later phase lands on, so it is browser-verified in all
four themes at the extremes of the text-size range before Phase 3 starts.

- [todo] P2.1: Four-theme token set, with per-theme status and accent shades
- [todo] P2.2: A rem type scale that one variable retunes
- [todo] P2.3: Sweep the 227 arbitrary pixel sizes onto the scale
- [todo] P2.4: appearanceStore, and a pre-paint script so nothing flashes
- [todo] P2.5: Contrast, focus rings and findable scrollbars
- [todo] P2.6: The 3D viewer follows the theme without remounting

## Phase 3: A place to change it

- [todo] P3.1: AppearanceFlyout: theme, accent, text size, density, motion
- [todo] P3.2: A palette control beside the cogwheel, in both rail states

## Phase 4: The rail and the dock stop fighting for room

- [todo] P4.1: The conversation list owns its own scroll, the rest are capped
- [todo] P4.2: CollapsibleSection expands before it acts on a header button
- [todo] P4.3: Storage becomes a gauge, and gives back two rows
- [todo] P4.4: The dock's collapsed strip reaches its own panels

## Phase 5: One search field, and a toolbar that earns its row

- [todo] P5.1: SearchField, replacing four near-identical copies
- [todo] P5.2: Archive as a toggle, plus status and engine filters
- [todo] P5.3: The four specs that pinned the old shapes

## Phase 6: Chat, sign-in, welcome, and the bugs found on the way

- [todo] P6.1: A chat header, and a readable measure
- [todo] P6.2: Sign-in and welcome carry the identity
- [todo] P6.3: Three real bugs found while reading the UI
- [todo] P6.4: The hairline and the engine hues, applied consistently

## Phase 7: Proof, docs, and the deployment

- [todo] P7.1: New specs for appearance, rail scroll and the collapsed plus
- [todo] P7.2: Contrast checked numerically in all four themes
- [todo] P7.3: README, screenshots and the architecture note
- [todo] P7.4: The dev stack rebuilt onto the new bundle

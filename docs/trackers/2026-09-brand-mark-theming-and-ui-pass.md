# Tracker: a brand mark, a theming system, and a critical UI pass

<!-- artifact: https://claude.ai/code/artifact/ae95965e-2faa-4223-abac-d4d62db6cac9 -->

**Complete, closed 2026-09-09, opened the same day.** Seven phases, all
merged, 27 steps. Gives NexusQC a logo it does not
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
- merged: 9d9c22c6886be02a5dce5bcbab2b4d1d9164e7b2

## Phase 2: Tokens, type scale, and the appearance store

The foundation every later phase lands on, so it is browser-verified in all
four themes at the extremes of the text-size range before Phase 3 starts.

- [done] P2.1: Four-theme token set, with per-theme status and accent shades
  evidence: tests/frontend/ui_14_contrast.spec.mjs → "204/204 pairs pass, reading computed tokens out of a live page in 4 themes x 5 accents; AA everywhere, AAA on Contrast. It caught six real failures on the first run: --status-cancelled was 3.86:1 on --surface-raised in three themes, and the periwinkle and violet accents were 5.8 and 6.6:1 on Contrast"
- [done] P2.2: A rem type scale that one variable retunes
  evidence: tests/frontend/ui_shots.mjs → "shell-balmer-fs09-1366.png and shell-balmer-fs135-1366.png show the same layout at 0.9 and 1.35; panel widths are stored in design pixels and rendered as rem so the sidebar grows with the text rather than holding 288 real pixels"
- [done] P2.3: Sweep the 227 arbitrary pixel sizes onto the scale
  evidence: grep -rn "text-\[" frontend/src → "no matches; 10px and 10.5px became text-3xs, 11px and 11.5px text-2xs, 12.5px text-xs, and the named steps each moved up one"
- [done] P2.4: appearanceStore, and a pre-paint script so nothing flashes
  evidence: tests/frontend/ui_shots.mjs → "every screenshot is produced by seeding localStorage and loading the page once, with no in-app interaction, so the four themed login screens are proof the inline script in index.html read the saved key before React mounted"
- [done] P2.5: Contrast, focus rings and findable scrollbars
  evidence: tests/frontend/ui_11_appearance.spec.mjs → "keyboard focus draws a visible ring: solid 2px, where before only the range inputs had one"
- [done] P2.6: The 3D viewer follows the theme without remounting
  evidence: tests/frontend/ui_11_appearance.spec.mjs → "the canvas toDataURL differs after a theme switch AND the canvas still carries the marker set on it beforehand, so it repainted rather than being rebuilt"
- merged: 7d726aa1e56639dc4a09db91261c864f1024e319

## Phase 3: A place to change it

- [done] P3.1: AppearanceFlyout: theme, accent, text size, density, motion
  evidence: tests/frontend/ui_11_appearance.spec.mjs → "26/26, including that the four theme cards preview in four different real background colours rather than four drawings, and that the sidebar grows from 288 to 389px at the largest text size"
- [done] P3.2: A palette control beside the cogwheel, in both rail states
  evidence: tests/frontend/ui_11_appearance.spec.mjs → "the palette control is in the sidebar header; it is rendered in the collapsed strip too, independently of UserMenu, which returns null when there is no user"
- merged: 7d726aa1e56639dc4a09db91261c864f1024e319

## Phase 4: The rail and the dock stop fighting for room

- [done] P4.1: The conversation list owns its own scroll, the rest are capped
  evidence: tests/frontend/ui_12_rail_scroll.spec.mjs → "12/12 with 26 seeded conversations: the list scrolls (scrollHeight 1660 vs clientHeight 589) and the Knowledge base, Files and Projects headers stay on screen, at the default text size and at the largest, where the old layout failed at about five conversations"
- [done] P4.2: CollapsibleSection expands before it acts on a header button
  evidence: tests/frontend/ui_13_collapsed_plus.spec.mjs → "23/23; the first run of this spec failed 9 of 15, because the new action prop passed the right state to the caller and never actually called onToggle. The bug it was written for was still there, in new code"
- [done] P4.3: Storage becomes a gauge, and gives back two rows
  evidence: tests/frontend/ui_shots.mjs → "shell-balmer-fs1-1920.png: the Knowledge base and Files headers carry a 14px ring instead of a subHeader row each, and the numbers appear as text only above 80 per cent"
- [done] P4.4: The dock's collapsed strip reaches its own panels
  evidence: tests/frontend/ui_13_collapsed_plus.spec.mjs → "all four icons open the dock with their own section expanded; they were inert divs with tooltips before"
- merged: 660fe4299ebc3828fa389a66580e81e0ee599998

## Phase 5: One search field, and a toolbar that earns its row

- [done] P5.1: SearchField, replacing four near-identical copies
  evidence: tests/frontend/jobs_01_search.spec.mjs → "11/11 driving the same input through the same testid, opened from its icon first; plots_01_panel 14/14 and up_02_files_and_attach 19/19 on the other two"
- [done] P5.2: Archive as a toggle, plus status and engine filters
  evidence: tests/frontend/ui_09_rail_and_jobmanager_controls.spec.mjs → "33/33, including that the search box does not exist until asked for and that opening it is the only thing that pushes the first job row down"
- [done] P5.3: The four specs that pinned the old shapes
  evidence: tests/frontend/proj_01_archive_roundtrip.spec.mjs → "40/40; page.check/uncheck needed a real checkbox, so it reads aria-pressed and clicks only when the state has to change"
- merged: 660fe4299ebc3828fa389a66580e81e0ee599998

## Phase 6: Chat, sign-in, welcome, and the bugs found on the way

- [done] P6.1: A chat header, and a readable measure
  evidence: tests/frontend/ui_15_identity_and_chat_header.spec.mjs → "the header names the conversation you are in and renames it inline, and the rename reaches the sidebar row; there was no header at all before, so with the sidebar collapsed the app could not say which conversation you were reading"
- [done] P6.2: Sign-in and welcome carry the identity
  evidence: tests/frontend/ui_15_identity_and_chat_header.spec.mjs → "the mark renders on the sign-in card and in the sidebar header; three hand-written wordmarks at three sizes and one lucide flask are gone"
- [done] P6.3: Three real bugs found while reading the UI
  evidence: tests/frontend/ui_15_identity_and_chat_header.spec.mjs → "the unsupported-engine cell is an en dash and no cell is a bare comma; and a walk of every text node and title attribute on the signed-in screen finds no ' -- ', which catches a new one wherever it appears rather than only where grep was pointed"
- [done] P6.4: The hairline and the engine hues, applied consistently
  evidence: tests/frontend/ui_shots.mjs → "shell-balmer-fs1-1920.png: pyscf teal and orca violet on the job rows, the active conversation carrying the hairline and a faint wash rather than a flat accent tint. The running row's hairline is the only thing in the app that animates unasked"
- merged: 1bd76c142cbd1826c8a745c7edd33f1e1d56f5c3

## Phase 7: Proof, docs, and the deployment

- [done] P7.1: New specs for appearance, rail scroll and the collapsed plus
  evidence: tests/frontend/ui_13_collapsed_plus.spec.mjs → "ui_11 26/26, ui_12 12/12, ui_13 23/23, ui_15 10/10, all against the compose stack on :8444"
- [done] P7.2: Contrast checked numerically in all four themes
  evidence: tests/frontend/ui_14_contrast.spec.mjs → "204/204 across 4 themes x 5 accents, AA everywhere and AAA on Contrast, with the status hues and the accent checked as text and not only as fills"
- [done] P7.3: README, screenshots and the architecture note
  evidence: tests/frontend/docs_shots.mjs → "docs/screenshot.png and docs/screenshot-results.png retaken from the live stack, the first driven through a real agent turn to the approval card; the README leads with the mark, and docs/ARCHITECTURE.md gained the theming contract and the viewer note"
- [done] P7.4: The dev stack rebuilt onto the new bundle
  evidence: scripts/extract_frontend.sh → "api image rebuilt and the bundle extracted, stamped 74e4af3622ff; the extracted bundle is byte-identical to a host npm run build (diff -rq, no differences), and ui_13 23/23, ui_15 10/10 and ui_14 204/204 pass against the recreated stack"
- merged: 1f6a665ef422da5e8c093ecf30c44222e5324141

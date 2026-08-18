// The frame scrubber, measured in real pixels against real frames.
//
// The claim under test is that the thumb width IS the frame count -- the thing
// that makes this control a scrollbar rather than a slider, and the reason it
// replaced an `<input type="range">` whose fixed thumb said nothing about the
// length of the series.
//
// Frames are built by resolving several molecules in one conversation:
// molecule_frames is an append-only log (app/agent/state.py), one entry per
// resolved molecule, so each turn adds exactly one. That costs a few LLM turns
// but it is the honest version -- asserting the arithmetic against a
// reimplementation of the same formula would test a copy of the code rather
// than the code.
import {
  newBrowser, freshContext, uiLogin, sendMessage, waitForComposerReady,
  check, summary, shot, ADMIN_USER, adminPassword,
} from "./_ui.mjs";

/** Thumb width as a fraction of its track, from laid-out geometry. */
async function thumbFraction(page) {
  return page.evaluate(() => {
    const thumb = document.querySelector('[data-testid="frame-scrubber-thumb"]');
    if (!thumb) return null;
    const track = thumb.parentElement;
    const t = thumb.getBoundingClientRect();
    const k = track.getBoundingClientRect();
    if (k.width === 0) return null;
    return {
      fraction: +(t.width / k.width).toFixed(3),
      left: +((t.left - k.left) / k.width).toFixed(3),
      right: +((t.right - k.left) / k.width).toFixed(3),
      thumbPx: Math.round(t.width),
    };
  });
}

const browser = await newBrowser();
const page = await (await freshContext(browser)).newPage();
// Four consecutive LLM turns on a shared host. sendMessage now waits on the
// Send button's own enabled state (see _ui.mjs), which is the real fix; this
// raises the remaining default action timeouts to match rather than leaving
// 30s ones scattered through a spec that is inherently slow.
page.setDefaultTimeout(180000);
await uiLogin(page, ADMIN_USER, adminPassword());
await waitForComposerReady(page);

// A fresh conversation, so frames from earlier scenarios do not leak in.
const newConv = page.locator('button[title="New conversation"]');
if (await newConv.count()) {
  await newConv.first().click();
  await page.waitForTimeout(1200);
}

const measured = [];

await sendMessage(page, "Set the molecule to water.");
await page.waitForTimeout(1500);
check("with a single frame the scrubber is not rendered at all (nothing to scrub)",
  (await page.locator('[data-testid="frame-scrubber"]').count()) === 0);

for (const [n, prompt] of [[2, "Now set the molecule to methane."],
                           [3, "Now set the molecule to ammonia."],
                           [4, "Now set the molecule to benzene."]]) {
  await sendMessage(page, prompt);
  await page.waitForTimeout(1800);
  const m = await thumbFraction(page);
  if (!m) { check(`frame ${n}: scrubber present`, false, "thumb not found"); continue; }
  measured.push({ n, ...m });
  console.log(`  ${n} frames -> thumb ${(m.fraction * 100).toFixed(1)}% of track (${m.thumbPx}px)`);
  // 1/n, within a pixel or two of rounding on a ~250px track.
  check(`with ${n} frames the thumb is about 1/${n} of the track`,
    Math.abs(m.fraction - 1 / n) < 0.04,
    `expected ~${(100 / n).toFixed(1)}%, measured ${(m.fraction * 100).toFixed(1)}%`);
  check(`with ${n} frames the thumb stays inside both bounds`,
    m.left >= -0.01 && m.right <= 1.01, `left=${m.left} right=${m.right}`);
}

check("the thumb shrank monotonically as frames were added",
  measured.length >= 2 && measured.every((m, i) => i === 0 || m.fraction < measured[i - 1].fraction),
  measured.map((m) => `${m.n}:${(m.fraction * 100).toFixed(1)}%`).join(" "));

await shot(page, "ui07-scrubber-4-frames");

// It is a scrollbar, so clicking the track jumps -- no drag needed.
const scrubber = page.locator('[data-testid="frame-scrubber"]').first();
const box = await scrubber.boundingBox();
if (box) {
  await page.mouse.click(box.x + box.width - 4, box.y + box.height / 2);
  await page.waitForTimeout(600);
  const atEnd = await page.locator('[data-testid="frame-stepper"]').first().innerText();
  check("clicking the right-hand end jumps to the last frame",
    /Frame\s+4\s*\/\s*4/.test(atEnd), atEnd.replace(/\s+/g, " ").slice(0, 60));

  await page.mouse.click(box.x + 2, box.y + box.height / 2);
  await page.waitForTimeout(600);
  const atStart = await page.locator('[data-testid="frame-stepper"]').first().innerText();
  check("clicking the left-hand end jumps to the first frame",
    /Frame\s+1\s*\/\s*4/.test(atStart), atStart.replace(/\s+/g, " ").slice(0, 60));
}

// No native range input should survive anywhere in the frame controls -- that
// is the control whose chrome ignored the palette in the first place.
const natives = await page.locator('[data-testid="frame-stepper"] input[type="range"]').count();
check("the frame controls contain no native range input", natives === 0, `${natives} found`);

await browser.close();
process.exit(summary() ? 0 : 1);

// Stepping through frames must not move the panel.
//
// Reported against a real pair: water, then uracil, whose SMILES
// ([H]c1c([H])n([H])c(=O)n([H])c1=O) is long enough that the old single-line
// header -- name, SMILES, charge, multiplicity and atom count together, in a
// flex child with no min-w-0 -- both widened the panel and wrapped to a second
// line. Every frame step therefore resized the panel and shifted the controls
// under the cursor.
//
// Measured, not eyeballed: the identity block's bounding box and the viewer's
// top edge are recorded at each frame and required to be identical. A header
// that grows by one line moves the viewer down, so the viewer's y is the
// sensitive witness.
import {
  newBrowser, freshContext, uiLogin, sendMessage, waitForComposerReady,
  check, summary, shot, ADMIN_USER, adminPassword,
} from "./_ui.mjs";

async function geometry(page) {
  return page.evaluate(() => {
    const header = document.querySelector('[data-testid="molecule-details-toggle"]')?.closest("div")?.parentElement;
    const canvas = document.querySelector("canvas");
    const scrubber = document.querySelector('[data-testid="frame-scrubber"]');
    const r = (el) => {
      if (!el) return null;
      const b = el.getBoundingClientRect();
      return { x: Math.round(b.x), y: Math.round(b.y), w: Math.round(b.width), h: Math.round(b.height) };
    };
    return { header: r(header), canvas: r(canvas), scrubber: r(scrubber) };
  });
}

const browser = await newBrowser();
const page = await (await freshContext(browser)).newPage();
page.setDefaultTimeout(180000);
await uiLogin(page, ADMIN_USER, adminPassword());
await waitForComposerReady(page);

const newConv = page.locator('button[title="New conversation"]');
if (await newConv.count()) {
  await newConv.first().click();
  await page.waitForTimeout(1200);
}

// Short name and short SMILES, then a long one. This is the reported pair.
await sendMessage(page, "Set the molecule to water.");
await page.waitForTimeout(1500);
await sendMessage(page, "Now set the molecule to uracil.");
await page.waitForTimeout(2500);

const scrubber = page.locator('[data-testid="frame-scrubber"]');
check("two frames produced a scrubber", (await scrubber.count()) > 0);

// ------------------------------------------------ geometry across frames
const prev = page.locator('[data-testid="frame-prev"]');
const next = page.locator('[data-testid="frame-next"]');

const seen = [];
for (const step of ["start", "prev", "next", "prev", "next"]) {
  if (step === "prev") await prev.first().click();
  if (step === "next") await next.first().click();
  await page.waitForTimeout(700);
  const g = await geometry(page);
  const label = await page.locator('[data-testid="frame-stepper"]').first().innerText();
  seen.push({ step, ...g, frame: label.replace(/\s+/g, " ").slice(0, 24) });
}

for (const s of seen) {
  console.log(`  ${s.step.padEnd(6)} ${s.frame.padEnd(24)} header=${JSON.stringify(s.header)} canvasTop=${s.canvas?.y}`);
}

const first = seen[0];
check("the identity block keeps exactly the same height on every frame",
  seen.every((s) => s.header && s.header.h === first.header.h),
  seen.map((s) => s.header?.h).join(" -> "));
check("the identity block keeps exactly the same width on every frame",
  seen.every((s) => s.header && s.header.w === first.header.w),
  seen.map((s) => s.header?.w).join(" -> "));
check("the viewer does not move down or up as frames change",
  seen.every((s) => s.canvas && s.canvas.y === first.canvas.y),
  seen.map((s) => s.canvas?.y).join(" -> "));
check("the viewer keeps the same width as frames change",
  seen.every((s) => s.canvas && s.canvas.w === first.canvas.w),
  seen.map((s) => s.canvas?.w).join(" -> "));
check("the scrubber itself does not move as frames change",
  seen.every((s) => s.scrubber && s.scrubber.y === first.scrubber.y),
  seen.map((s) => s.scrubber?.y).join(" -> "));

await shot(page, "ui08-frame-stability");

// ------------------------------------------------ details panel
const toggle = page.locator('[data-testid="molecule-details-toggle"]').first();
check("the second line is a details toggle", (await toggle.count()) > 0);
check("details start collapsed", (await page.locator('[data-testid="molecule-details"]').count()) === 0);

await toggle.click();
await page.waitForTimeout(400);
const details = page.locator('[data-testid="molecule-details"]').first();
check("clicking it reveals the details", (await details.count()) > 0);

const detailText = await details.innerText();
console.log(`  details: ${detailText.replace(/\s+/g, " ").slice(0, 120)}`);
check("details list charge, multiplicity, atoms and SMILES, in that order",
  /Charge[\s\S]*Multiplicity[\s\S]*Atoms[\s\S]*SMILES/i.test(detailText),
  detailText.replace(/\s+/g, " ").slice(0, 90));
check("the long SMILES is in the details, not the header",
  /c1c/i.test(detailText), detailText.replace(/\s+/g, " ").slice(0, 90));

// Open, the panel may be taller -- but it must still be STABLE while stepping.
const openGeom = [];
for (const step of ["start", "prev", "next"]) {
  if (step !== "start") await page.locator(`[data-testid="frame-${step}"]`).first().click();
  await page.waitForTimeout(700);
  openGeom.push(await geometry(page));
}
check("with details open, stepping frames still does not move the viewer",
  openGeom.every((g) => g.canvas && g.canvas.y === openGeom[0].canvas.y),
  openGeom.map((g) => g.canvas?.y).join(" -> "));

await toggle.click();
await page.waitForTimeout(400);

// ------------------------------------------------ arrow keys after a click
// The scrubber sets tabIndex and handles arrows, but its pointerdown calls
// preventDefault() to stop text selection during a drag -- which also
// suppressed the browser's default focus-on-mousedown, so clicking it never
// focused it and the arrow keys went nowhere.
const box = await scrubber.first().boundingBox();
await page.mouse.click(box.x + 2, box.y + box.height / 2); // jump to frame 1
await page.waitForTimeout(500);

const focused = await page.evaluate(() =>
  document.activeElement?.getAttribute("data-testid") ?? document.activeElement?.tagName ?? null);
check("clicking the scrubber focuses it", focused === "frame-scrubber", `activeElement=${focused}`);

const before = await page.locator('[data-testid="frame-stepper"]').first().innerText();
await page.keyboard.press("ArrowRight");
await page.waitForTimeout(500);
const afterRight = await page.locator('[data-testid="frame-stepper"]').first().innerText();
check("ArrowRight advances a frame after clicking the scrubber",
  /Frame\s+2\s*\/\s*2/.test(afterRight),
  `${before.replace(/\s+/g, " ").slice(0, 20)} -> ${afterRight.replace(/\s+/g, " ").slice(0, 20)}`);

await page.keyboard.press("ArrowLeft");
await page.waitForTimeout(500);
const afterLeft = await page.locator('[data-testid="frame-stepper"]').first().innerText();
check("ArrowLeft goes back a frame", /Frame\s+1\s*\/\s*2/.test(afterLeft),
  afterLeft.replace(/\s+/g, " ").slice(0, 20));

await page.keyboard.press("End");
await page.waitForTimeout(400);
check("End jumps to the last frame",
  /Frame\s+2\s*\/\s*2/.test(await page.locator('[data-testid="frame-stepper"]').first().innerText()));
await page.keyboard.press("Home");
await page.waitForTimeout(400);
check("Home jumps to the first frame",
  /Frame\s+1\s*\/\s*2/.test(await page.locator('[data-testid="frame-stepper"]').first().innerText()));

await browser.close();
process.exit(summary() ? 0 : 1);

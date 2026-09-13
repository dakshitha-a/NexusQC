// P3.2: getting a molecule in. By name (PubChem then OPSIN), by SMILES
// including the charset trap, by pasted XYZ, by an attached file with one,
// two and many geometries, and reset. Then: are atom numbers 1-based
// everywhere the user sees them, do the viewer controls work, does the
// atom-label toggle draw anything.
//
//   QC_REVIEW_ACCOUNTS=<scratchpad>/review-accounts.json \
//   node docs/evaluation/2026-09-app-review/evidence/p3/p3_02_molecule_in.mjs
import fs from "node:fs";
import path from "node:path";
import { start, loginAs, Log, sendMessage, transcript, allCanvases, EVIDENCE, BASE_URL } from "./_p3.mjs";

const L = new Log("p3_02_molecule_in");
const browser = await start();
const { ctx, page } = await loginAs(browser, "qa_review");

// Fresh conversation so nothing from another step is in scope.
await L.observe(page, "new-conversation", async () => {
  const b = page.locator('[data-testid="conversation-new"]');
  if (await b.count()) await b.click();
  await page.waitForTimeout(800);
  return {};
});

async function turn(name, text, { timeout = 300000 } = {}) {
  return L.observe(page, name, async () => {
    const t = Date.now();
    await sendMessage(page, text, { timeout });
    const ms = Date.now() - t;
    const tail = (await transcript(page)).slice(-2500);
    const canvases = await allCanvases(page);
    return { turn_ms: ms, reply_tail: tail, canvases, console: page.__console.splice(0) };
  });
}

// --- by name ---------------------------------------------------------------
await turn("name-water", "Load water as the molecule, please.");
await turn("name-caffeine-pubchem", "Switch the molecule to caffeine.");
// OPSIN handles systematic names PubChem may not; this one is deliberately IUPAC.
await turn("name-iupac-opsin", "Make the molecule 2-methylpropan-2-ol.");
// A name that does not exist anywhere.
await turn("name-nonsense", "Load the molecule flurbogastrin.");

// --- by SMILES, including the charset trap -----------------------------------
await turn("smiles-ethanol", "Use this SMILES as the molecule: CCO");
// Lowercase aromatic, ring closure digits, a charge and a bracket atom: the
// characters that have historically confused the name/SMILES sniffing.
await turn("smiles-charset-trap", "Set the molecule from SMILES: c1ccccc1[N+](=O)[O-]");
// A SMILES that is also, plausibly, a word.
await turn("smiles-looks-like-word", "Molecule: CO");

// --- pasted XYZ --------------------------------------------------------------
const xyz1 = `3
water, pasted
O   0.000000   0.000000   0.117300
H   0.000000   0.757200  -0.469200
H   0.000000  -0.757200  -0.469200`;
await turn("xyz-pasted-single", `Here is a geometry, use it as the molecule:\n\n${xyz1}`);

// Ask for a geometry parameter using atom numbers. 1-based means O is atom 1
// and H are 2 and 3; the H-O-H angle is then atoms 2-1-3.
await turn("atom-numbers-angle", "What is the angle between atoms 2, 1 and 3?");
await turn("atom-numbers-bond", "What is the distance between atom 1 and atom 2?");
// The trap: if numbering leaked 0-based anywhere, "atom 0" would be accepted.
await turn("atom-zero-should-be-refused", "What is the distance between atom 0 and atom 1?");

// --- attached files: one, two, many geometries -------------------------------
const tmp = path.join(EVIDENCE, "p3_02_molecule_in");
fs.mkdirSync(tmp, { recursive: true });
const one = path.join(tmp, "one.xyz"); fs.writeFileSync(one, xyz1 + "\n");
const two = path.join(tmp, "two.xyz");
fs.writeFileSync(two, xyz1 + "\n" + xyz1.replace("0.117300", "0.217300").replace("water, pasted", "water, stretched") + "\n");
let many = "";
for (let i = 0; i < 5; i++) many += xyz1.replace("0.117300", (0.1173 + 0.02 * i).toFixed(6)).replace("water, pasted", `frame ${i + 1}`) + "\n";
const manyF = path.join(tmp, "many.xyz"); fs.writeFileSync(manyF, many);

async function attach(name, file, prompt) {
  return L.observe(page, name, async () => {
    const input = page.locator('[data-testid="composer-file-input"]');
    await input.setInputFiles(file);
    await page.waitForTimeout(1200);
    const note = await page.locator('[data-testid="composer-upload-note"]').innerText().catch(() => null);
    const t = Date.now();
    await sendMessage(page, prompt, { timeout: 300000 });
    return { upload_note: note, turn_ms: Date.now() - t, reply_tail: (await transcript(page)).slice(-2500), canvases: await allCanvases(page), console: page.__console.splice(0) };
  });
}
await attach("attach-one-geometry", one, "Use the attached file as the molecule.");
await attach("attach-two-geometries", two, "I've attached two geometries. What can you do with them?");
await attach("attach-many-geometries", manyF, "I've attached five geometries.");

// The geometry-set viewer: can I step through frames and tag one?
await L.observe(page, "geometry-set-controls", async () => {
  const next = page.locator('[data-testid="frame-next"]');
  const tag = page.locator('[data-testid="geometry-set-tag-frame"]');
  const scrub = page.locator('[data-testid="frame-scrubber"]');
  const before = await allCanvases(page);
  if (await next.count()) { await next.first().click(); await page.waitForTimeout(500); }
  const after = await allCanvases(page);
  return { has_next: await next.count(), has_tag: await tag.count(), has_scrubber: await scrub.count(), canvas_before: before, canvas_after: after };
});

// --- reset --------------------------------------------------------------------
await turn("reset-molecule", "Clear the molecule.");

// --- viewer controls and the atom-label toggle --------------------------------
await turn("reload-water-for-viewer", "Load water again.");
await L.observe(page, "viewer-controls-inventory", async () => {
  const titles = await page.evaluate(() =>
    Array.from(document.querySelectorAll("button[title]")).map((b) => b.getAttribute("title")).filter(Boolean));
  return { control_titles: [...new Set(titles)] };
});
await L.observe(page, "atom-labels-on", async () => {
  const before = await allCanvases(page);
  const t = page.locator('button[title*="label" i], button[title*="number" i], [aria-label*="label" i]').first();
  const found = await t.count();
  if (found) await t.click();
  await page.waitForTimeout(800);
  const after = await allCanvases(page);
  return { toggle_found: found > 0, before, after, changed: JSON.stringify(before) !== JSON.stringify(after) };
});
await L.observe(page, "molecule-details", async () => {
  const tog = page.locator('[data-testid="molecule-details-toggle"]');
  if (await tog.count()) await tog.click();
  await page.waitForTimeout(400);
  const d = await page.locator('[data-testid="molecule-details"]').innerText().catch(() => null);
  return { details: d && d.slice(0, 1500) };
});

L.note(`api requests this session: ${page.__requests.length}`);
fs.writeFileSync(path.join(L.shotDir, "requests.json"), JSON.stringify(page.__requests, null, 1));
await ctx.close();
await browser.close();
console.log(`\nevidence: ${L.file}\nscreenshots: ${L.shotDir}/`);

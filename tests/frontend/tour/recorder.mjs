// Frames for the README's animations, and where the camera should look.
//
// Ported from NextTex's e2e/shots/recorder.ts on 2026-10-22, as plain
// JavaScript for this directory's raw-playwright house style.
//
// The browser is filmed through the DevTools screencast, which sends a frame
// each time the page repaints, with the time it painted. A scene that sits
// still costs nothing and one that types costs a frame a keystroke. Every
// frame is the whole viewport at full resolution; the zooming is not done
// here. The scene says what matters and when, with focus() and wide(), and
// animate.py turns those marks into a camera that glides between them,
// cropping the full frames, so a zoomed view is as sharp as the screen was.
//
// The screencast also captures the 3Dmol WebGL canvases, which
// page.screenshot() does not reliably do (CLAUDE.md). Checked on 2026-10-22
// with benzene in the molecule pane.
//
// Headless Chromium draws no mouse pointer, and an animation where things
// are clicked by nobody is hard to follow, so install() puts a drawn pointer
// on the page that follows the real one and pulses on a click.
import { mkdirSync, rmSync, writeFileSync } from "node:fs";
import { join } from "node:path";

const POINTER = `
(() => {
  if (window.__nxPointer) return;
  window.__nxPointer = true;
  const start = () => {
    const dot = document.createElement("div");
    dot.setAttribute("aria-hidden", "true");
    dot.style.cssText = "position:fixed;left:0;top:0;width:22px;height:22px;z-index:2147483647;pointer-events:none;transform:translate(-100px,-100px);transition:transform 40ms linear";
    dot.innerHTML = '<svg width="22" height="22" viewBox="0 0 22 22"><path d="M3 2l14 8.2-6.3 1.3 3.6 7.1-2.6 1.3-3.6-7.2L3 17z" fill="#fff" stroke="#1b1f1d" stroke-width="1.4" stroke-linejoin="round"/></svg>';
    const ring = document.createElement("div");
    ring.style.cssText = "position:fixed;left:0;top:0;width:34px;height:34px;margin:-17px 0 0 -17px;border-radius:50%;border:2.5px solid #2ec8e6;z-index:2147483646;pointer-events:none;opacity:0;transform:scale(.4)";
    document.documentElement.append(ring, dot);
    let x = -100, y = -100;
    addEventListener("mousemove", (e) => { x = e.clientX; y = e.clientY; dot.style.transform = "translate(" + (x - 3) + "px," + (y - 2) + "px)"; }, true);
    addEventListener("mousedown", () => {
      ring.style.left = x + "px"; ring.style.top = y + "px";
      ring.animate([{ opacity: .9, transform: "scale(.4)" }, { opacity: 0, transform: "scale(1.3)" }], { duration: 420, easing: "ease-out" });
    }, true);
  };
  if (document.documentElement) start(); else addEventListener("DOMContentLoaded", start);
})();`;

export class Recorder {
  constructor(page, name, root) {
    this.page = page;
    this.name = name;
    this.root = root;
    this.session = null;
    this.frames = [];
    this.marks = [];
    this.fast = [];
    this.t0 = 0;
    this.dir = "";
    this.count = 0;
  }

  /** The drawn pointer, on this page and on every page it loads next. */
  static async install(page) {
    await page.addInitScript(POINTER);
    await page.evaluate(POINTER).catch(() => undefined);
  }

  async start() {
    this.dir = join(this.root, this.name);
    rmSync(this.dir, { recursive: true, force: true });
    mkdirSync(this.dir, { recursive: true });
    const viewport = this.page.viewportSize();
    const scale = await this.page.evaluate(() => window.devicePixelRatio);
    this.session = await this.page.context().newCDPSession(this.page);
    this.t0 = Date.now() / 1000;
    // JPEG at a high quality rather than PNG, and the frame acknowledged
    // before it is written, since the browser sends no next frame until the
    // last is acknowledged. The frames are scaled down on the way out, which
    // hides what JPEG at 94 loses.
    this.session.on("Page.screencastFrame", async (frame) => {
      const file = `f${String(this.count++).padStart(5, "0")}.jpg`;
      const t = (frame.metadata.timestamp ?? Date.now() / 1000) - this.t0;
      await this.session?.send("Page.screencastFrameAck", { sessionId: frame.sessionId }).catch(() => undefined);
      writeFileSync(join(this.dir, file), Buffer.from(frame.data, "base64"));
      this.frames.push({ t, file });
    });
    await this.session.send("Page.startScreencast", {
      format: "jpeg",
      quality: 94,
      maxWidth: Math.round(viewport.width * scale),
      maxHeight: Math.round(viewport.height * scale),
      everyNthFrame: 1,
    });
    // A repaint to be sure the first frame is the opening one.
    await this.page.evaluate(() => document.body.style.setProperty("--nx-rec", "1"));
    await this.page.waitForTimeout(250);
  }

  now() {
    return Date.now() / 1000 - this.t0;
  }

  /** Glide the camera to this element (a Locator or a {x,y,width,height}
   *  rectangle), padded, over `ease` seconds. `zoom` lifts the camera's
   *  closest approach for this mark alone. */
  async focus(target, opts = {}) {
    const box = "x" in target ? target : await target.boundingBox();
    if (!box) throw new Error(`${this.name}: nothing to focus on`);
    const pad = opts.pad ?? 40;
    this.marks.push({
      t: this.now(),
      kind: "focus",
      rect: { x: box.x - pad, y: box.y - pad, width: box.width + 2 * pad, height: box.height + 2 * pad },
      ease: opts.ease ?? 0.7,
      ...(opts.zoom ? { zoom: opts.zoom } : {}),
    });
  }

  /** Pull back to the whole window. */
  wide(ease = 0.7) {
    this.marks.push({ t: this.now(), kind: "wide", ease });
  }

  /** Wait for something slow, a model reply or a running job, and play the
   *  wait back faster, so the animation spends its seconds on what happens
   *  rather than on the wait for it. */
  async quickly(wait, speed = 5) {
    const from = this.now();
    const result = await wait();
    this.fast.push({ from, to: this.now(), speed });
    return result;
  }

  async hold(ms) {
    await this.page.waitForTimeout(ms);
  }

  async stop() {
    await this.page.waitForTimeout(300);
    await this.session?.send("Page.stopScreencast").catch(() => undefined);
    await this.page.waitForTimeout(200);
    await this.session?.detach().catch(() => undefined);
    const viewport = this.page.viewportSize();
    writeFileSync(
      join(this.dir, "scene.json"),
      JSON.stringify({ name: this.name, viewport, end: this.now(), frames: this.frames, marks: this.marks, fast: this.fast }, null, 1),
    );
  }
}

/** The smallest rectangle around every given locator. */
export async function span(...targets) {
  const boxes = (await Promise.all(targets.map((t) => t.boundingBox()))).filter(Boolean);
  if (!boxes.length) throw new Error("nothing to span");
  const x = Math.min(...boxes.map((b) => b.x));
  const y = Math.min(...boxes.map((b) => b.y));
  const r = Math.max(...boxes.map((b) => b.x + b.width));
  const b = Math.max(...boxes.map((b) => b.y + b.height));
  return { x, y, width: r - x, height: b - y };
}

/** Move the drawn pointer to an element the way a hand would, in steps. */
export async function glide(page, target, steps = 18) {
  const box = await target.boundingBox();
  if (!box) throw new Error("nothing to point at");
  const x = box.x + box.width / 2;
  const y = box.y + box.height / 2;
  await page.mouse.move(x, y, { steps });
  return { x, y };
}

/** Type like a person: a short pause between keys. */
export async function typeOut(locator, text, delay = 28) {
  await locator.pressSequentially(text, { delay });
}

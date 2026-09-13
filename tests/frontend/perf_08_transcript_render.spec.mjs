// R-067: what a single streamed token costs the transcript.
//
// The finding, from a code read: ChatPane subscribes to the whole chat store
// with no selector, the store writes a new `streaming` object on every token,
// and ChatPane maps the entire message history through an unmemoised
// component whose assistant branch runs a full remark parse of that message's
// markdown from scratch on every render. On a long conversation that is one
// complete re-render of every message, and one markdown parse per assistant
// message, per token.
//
// HOW THIS IS MEASURED, and why it is not driven by a real agent turn.
//
// A real turn's length and timing depend on the model, so two runs are not
// comparable and the number would not be reproducible by anyone else. The app
// receives its tokens over an EventSource (frontend/src/lib/sse.ts), so this
// spec replaces window.EventSource before any app code loads and drives the
// transcript itself. Every run then sees exactly the same input:
//
//   - TRANSCRIPT_MESSAGES synthetic messages are pushed in as `message`
//     events, alternating human and assistant, each assistant message
//     carrying real markdown (a heading, a list, a fenced code block, a
//     table) so the remark parse has something to do. This is what a working
//     conversation looks like by the time the cost matters.
//   - Then TOKEN_COUNT `token` events are pushed one animation frame apart,
//     which is the same shape as a stream arriving faster than the browser
//     can paint. The rate is fixed, so the work per token is what varies.
//
// The number reported is Chrome's own ScriptDuration, read through the
// DevTools Protocol (Performance.getMetrics) immediately before the token
// phase and immediately after it. That is cumulative seconds of JavaScript
// execution on the main thread, so it counts React's render and commit and
// the markdown parses inside them, and it does not count paint or network.
// RecalcStyleDuration and LayoutDuration are reported alongside it because a
// re-render that produces identical output still costs style and layout work,
// and it is worth seeing that fall too.
//
// REPS runs are taken and the median reported, because the first run of
// anything in a fresh page pays for JIT warmup that is not part of what is
// being measured.
//
// This is a measurement, not a pass/fail assertion about a threshold. It
// prints its numbers and asserts only that the harness did what it claims:
// the transcript reached the expected length and the token phase ran. Compare
// the two runs, one against the deployed bundle before the fix and one after,
// and put both numbers in the write-up.
//
//   QC_AGENT_TEST_BASE_URL=https://127.0.0.1:8444 \
//     node tests/frontend/perf_08_transcript_render.spec.mjs
//
// The label written into the output is set with QC_AGENT_PERF_LABEL, e.g.
// `QC_AGENT_PERF_LABEL=before`.
import {
  newBrowser, newContext, adminApiLogin, mintInvite, check, summary, BASE_URL,
} from "./_helpers.mjs";

const TRANSCRIPT_MESSAGES = 40;
const TOKEN_COUNT = 300;
const REPS = 3;
const RUN_LABEL = process.env.QC_AGENT_PERF_LABEL || "unlabelled";

const median = (xs) => {
  const s = [...xs].sort((a, b) => a - b);
  return s.length % 2 ? s[(s.length - 1) / 2] : (s[s.length / 2 - 1] + s[s.length / 2]) / 2;
};

async function main() {
  const browser = await newBrowser();
  const adminCtx = await newContext(browser);
  await adminApiLogin(adminCtx);
  const token = await mintInvite(adminCtx, "user");
  const username = "qatest_perf08_" + Math.random().toString(36).slice(2, 8);
  const password = "correct horse battery staple 1";

  const ctx = await newContext(browser);
  const page = await ctx.newPage();

  // Installed before any app module evaluates, so sse.ts constructs this
  // instead of the real thing. It never opens a connection; the spec is the
  // only source of events.
  await page.addInitScript(() => {
    class FakeEventSource {
      constructor(url) {
        this.url = url;
        this.readyState = 1;
        this._listeners = {};
        window.__fakeES = this;
        // sse.ts keys readiness off onopen, so fire it on the next tick.
        setTimeout(() => { if (this.onopen) this.onopen(new Event("open")); }, 0);
      }
      addEventListener(type, fn) {
        if (!this._listeners[type]) this._listeners[type] = [];
        this._listeners[type].push(fn);
      }
      removeEventListener(type, fn) {
        this._listeners[type] = (this._listeners[type] || []).filter((f) => f !== fn);
      }
      close() { this.readyState = 2; }
      /** What the spec calls to push one server event in. */
      __emit(type, payload) {
        const e = new MessageEvent(type, { data: JSON.stringify(payload) });
        for (const fn of this._listeners[type] || []) fn(e);
      }
    }
    window.EventSource = FakeEventSource;
  });

  const consoleErrors = [];
  page.on("console", (m) => { if (m.type() === "error") consoleErrors.push(m.text()); });
  page.on("pageerror", (e) => consoleErrors.push(String(e)));

  try {
    console.log(`\n== run label: ${RUN_LABEL} ==`);
    console.log("\n== register + log in ==");
    await page.goto(`${BASE_URL}/?invite=${token}`, { waitUntil: "domcontentloaded" });
    await page.fill('input[placeholder="Email"]', `${username}@example.test`);
    await page.fill('input[placeholder="Username"]', username);
    await page.fill('input[placeholder="First name"]', "QA");
    await page.fill('input[placeholder="Last name"]', "Tester");
    await page.fill('input[placeholder="Password"]', password);
    await page.click('button[type="submit"]');
    await page.waitForSelector('[data-testid="user-menu-open"]', { timeout: 20000 });
    check("registered and logged in", true);
    consoleErrors.length = 0;

    // A thread has to be active for sse.ts to construct its EventSource.
    await page.click('[data-testid="conversation-new"]');
    await page.waitForTimeout(2500);
    const haveStream = await page.evaluate(() => !!window.__fakeES);
    check("the app opened its event stream through the spec's EventSource", haveStream);
    if (!haveStream) throw new Error("no EventSource was constructed, nothing to drive");

    const cdp = await ctx.newCDPSession(page);
    await cdp.send("Performance.enable");
    const metric = async (name) => {
      const { metrics } = await cdp.send("Performance.getMetrics");
      return (metrics.find((m) => m.name === name) || {}).value ?? 0;
    };

    const results = [];
    for (let rep = 0; rep < REPS; rep++) {
      // Fresh transcript each rep: reload, re-open a conversation, refill.
      if (rep > 0) {
        await page.reload({ waitUntil: "domcontentloaded" });
        await page.waitForSelector('[data-testid="user-menu-open"]', { timeout: 20000 });
        await page.click('[data-testid="conversation-new"]');
        await page.waitForTimeout(2500);
      }

      const built = await page.evaluate(async (n) => {
        const es = window.__fakeES;
        const body = [
          "## What this run showed",
          "",
          "- the SCF converged in 11 cycles",
          "- the final energy is **-76.02** Hartree",
          "- the dipole is 1.85 D, close to the experimental 1.85 D",
          "",
          "| quantity | value |",
          "| --- | --- |",
          "| E(SCF) | -76.0267 |",
          "| HOMO | -0.4941 |",
          "",
          "```",
          "converged SCF energy = -76.0267326 ",
          "```",
          "",
          "Ask for a frequency run next if you want the zero-point correction.",
        ].join("\n");
        for (let i = 0; i < n; i++) {
          const human = i % 2 === 0;
          es.__emit("message", {
            type: "message",
            message: {
              id: `seed-${i}`,
              type: human ? "HumanMessage" : "AIMessage",
              content: human ? `run water at hf/sto-3g, attempt ${i}` : body,
              name: null,
              tool_call_id: null,
              tool_calls: [],
            },
          });
          // Let React commit, so the transcript is really in the DOM rather
          // than one batched update at the end.
          if (i % 8 === 7) await new Promise((r) => setTimeout(r, 0));
        }
        await new Promise((r) => setTimeout(r, 600));
        // No stable testid on the transcript container, so count the
        // rendered markdown headings instead: one per seeded assistant
        // message, and they only exist if the message really rendered.
        return document.querySelectorAll("h2").length;
      }, TRANSCRIPT_MESSAGES);

      const scriptBefore = await metric("ScriptDuration");
      const styleBefore = await metric("RecalcStyleDuration");
      const layoutBefore = await metric("LayoutDuration");

      const wall = await page.evaluate(async (n) => {
        const es = window.__fakeES;
        const t0 = performance.now();
        for (let i = 0; i < n; i++) {
          es.__emit("token", { type: "token", message_id: "streaming-1", delta: "word " });
          await new Promise((r) => requestAnimationFrame(r));
        }
        await new Promise((r) => setTimeout(r, 300));
        return performance.now() - t0;
      }, TOKEN_COUNT);

      const script = (await metric("ScriptDuration")) - scriptBefore;
      const style = (await metric("RecalcStyleDuration")) - styleBefore;
      const layout = (await metric("LayoutDuration")) - layoutBefore;
      results.push({ script, style, layout, wall, built });
      console.log(
        `  rep ${rep + 1}: script ${(script * 1000).toFixed(0)} ms, ` +
        `style ${(style * 1000).toFixed(0)} ms, layout ${(layout * 1000).toFixed(0)} ms, ` +
        `wall ${wall.toFixed(0)} ms (transcript children rendered: ${built})`,
      );
    }

    const perToken = (v) => (v * 1000) / TOKEN_COUNT;
    const medScript = median(results.map((r) => r.script));
    const medStyle = median(results.map((r) => r.style));
    const medLayout = median(results.map((r) => r.layout));

    console.log(
      `\nRESULT label=${RUN_LABEL} messages=${TRANSCRIPT_MESSAGES} tokens=${TOKEN_COUNT} reps=${REPS}\n` +
      `  median ScriptDuration over the token phase: ${(medScript * 1000).toFixed(0)} ms ` +
      `(${perToken(medScript).toFixed(2)} ms per token)\n` +
      `  median RecalcStyleDuration:                 ${(medStyle * 1000).toFixed(0)} ms ` +
      `(${perToken(medStyle).toFixed(2)} ms per token)\n` +
      `  median LayoutDuration:                      ${(medLayout * 1000).toFixed(0)} ms ` +
      `(${perToken(medLayout).toFixed(2)} ms per token)`,
    );

    // Half of TRANSCRIPT_MESSAGES are assistant messages, and each renders
    // exactly one <h2> from its markdown heading.
    check("every rep rendered a transcript of the expected length",
      results.every((r) => r.built >= TRANSCRIPT_MESSAGES / 2),
      results.map((r) => r.built).join(", "));
    check("the token phase ran in every rep", results.every((r) => r.wall > 0));
    check("no console errors during the measurement", consoleErrors.length === 0,
      consoleErrors.slice(0, 3).join(" | "));
  } finally {
    await browser.close();
  }
  process.exit(summary() ? 0 : 1);
}

main();

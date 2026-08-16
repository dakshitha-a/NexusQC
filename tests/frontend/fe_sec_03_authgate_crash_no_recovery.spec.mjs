// FE-SEC-03 (fix regression test): App.tsx now wraps the WHOLE tree
// (AuthGate + ShellLayout) in a PanelErrorBoundary -- originally, every
// boundary in the app lived INSIDE ShellLayout, so a render-time exception
// in AuthGate/LoginScreen itself (rendered BEFORE ShellLayout ever mounts)
// took down the entire page with no recovery UI, confirmed via this exact
// injected-exception technique before the fix landed. Note: AuthGate's own
// useQuery error handling (frontend/src/auth/AuthGate.tsx) already handled
// fetch/HTTP errors gracefully even before the fix (shows "Could not reach
// the server..." for a generic error, LoginScreen for a 401) -- that was
// never the gap; the gap was specifically an uncaught RENDER exception.
//
// Proof: page.addInitScript patches window.URLSearchParams (used directly
// in LoginScreen's useState initializers, unconditionally, on every
// render of that component) to throw. This reproduces the SAME failure
// class as a real bug would (any exception thrown during LoginScreen's
// render) without depending on a specific unlikely input. Now checks that
// the boundary catches it (no uncaught pageerror event -- React's error
// boundary machinery handles it internally via componentDidCatch instead
// of letting it propagate) and shows the same "Try again" recovery UI
// every other panel in this app already has, contrasted with a CONTROL
// case (a real network failure on GET /api/auth/me, handled by AuthGate's
// own query-error branch, not this boundary at all).
import { newBrowser, newContext, check, summary, BASE_URL } from "./_helpers.mjs";

async function main() {
  const browser = await newBrowser();

  // --- Control case: a real network-level failure on getMe IS handled gracefully ---
  const ctxControl = await newContext(browser);
  const pageControl = await ctxControl.newPage();
  await pageControl.route("**/api/auth/me", (route) => route.abort("failed"));
  await pageControl.goto(BASE_URL);
  await pageControl.waitForTimeout(1500);
  const controlBodyText = await pageControl.locator("body").innerText();
  check(
    "CONTROL: a network failure on GET /api/auth/me shows a graceful error message, not a blank page",
    /could not reach the server/i.test(controlBodyText),
    controlBodyText.slice(0, 200),
  );
  await pageControl.close();
  await ctxControl.close();

  // --- The actual finding: an unhandled render exception in LoginScreen ---
  const ctxCrash = await newContext(browser);
  const pageCrash = await ctxCrash.newPage();
  const consoleErrors = [];
  pageCrash.on("pageerror", (err) => consoleErrors.push(String(err)));
  await pageCrash.addInitScript(() => {
    // eslint-disable-next-line no-undef
    window.URLSearchParams = class {
      constructor() {
        throw new Error("FE-SEC-03 injected render-time exception");
      }
    };
  });
  await pageCrash.goto(BASE_URL);
  await pageCrash.waitForTimeout(2000);

  const bodyText = await pageCrash.locator("body").innerText().catch(() => "");
  const hasRecoveryUi = /try again/i.test(bodyText);

  console.log(`uncaught page errors: ${consoleErrors.length} (0 is expected now -- the boundary catches it internally)`);
  console.log(`body text after crash: ${JSON.stringify(bodyText.slice(0, 200))}`);

  check(
    "FIX VERIFIED: the injected exception does NOT propagate as an uncaught page error (the boundary caught it)",
    consoleErrors.length === 0,
    consoleErrors[0]?.slice(0, 200),
  );
  check(
    "FIX VERIFIED: a 'Try again' recovery UI is shown instead of a blank page",
    hasRecoveryUi,
    hasRecoveryUi ? bodyText.slice(0, 100) : `body has no recovery UI: ${JSON.stringify(bodyText.slice(0, 100))}`,
  );

  // The boundary's "Try again" just clears local error state and
  // re-renders the same children -- with the injected fault still active
  // (this page's URLSearchParams patch is permanent for its lifetime), it
  // should throw again immediately rather than getting stuck in some
  // broken in-between state.
  const tryAgainButton = pageCrash.locator('button:has-text("Try again")');
  if (await tryAgainButton.count()) {
    await tryAgainButton.click();
    await pageCrash.waitForTimeout(500);
    const afterRetry = await pageCrash.locator("body").innerText().catch(() => "");
    check("clicking 'Try again' re-renders cleanly (still shows recovery UI, not a broken state)", /try again/i.test(afterRetry));
  }

  await browser.close();
  const ok = summary();
  process.exit(ok ? 0 : 1);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});

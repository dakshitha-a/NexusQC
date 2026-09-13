import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import "./index.css";
// Imported for its side effect as well as its exports: the module stamps the
// saved theme, accent, text size, density and motion onto <html> at load and
// subscribes for later changes. Doing it here rather than from a component
// effect means the sign-in screen, which renders before the shell exists, is
// already themed.
import "./lib/appearanceStore.ts";
import App from "./App.tsx";
import { registerAuthErrorHandler } from "./lib/api.ts";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      // No GLOBAL refetch interval. Individual queries set their own where
      // there is a reason -- lib/queries.ts does so about a dozen times, for
      // the panels SSE cannot keep fresh (the cross-conversation Job Manager
      // has no per-thread stream to be invalidated by) and as a fallback for
      // the ones it can, so a dropped stream does not leave the UI silently
      // stale for the rest of an outage.
      //
      // This comment used to say refetchInterval "is deliberately never set
      // on any query in this app", which had not been true for a long time
      // (R-094). staleTime just avoids redundant refetches on component
      // remount for data that has not been invalidated.
      staleTime: 10_000,
      retry: 1,
    },
  },
});

// Any authenticated call that gets a 401 (session expired, or superseded
// by a login elsewhere) invalidates AuthGate's getMe query -- the same
// query it already re-fetches on its own staleTime schedule, just forced
// immediately instead of waiting. AuthGate's existing error branch then
// takes it from there (shows LoginScreen) with no new logic needed there.
registerAuthErrorHandler(() => {
  queryClient.invalidateQueries({ queryKey: ["auth", "me"] });
});

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <App />
    </QueryClientProvider>
  </StrictMode>,
);

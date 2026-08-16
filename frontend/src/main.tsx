import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import "./index.css";
import App from "./App.tsx";
import { registerAuthErrorHandler } from "./lib/api.ts";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      // Job/thread/state data is kept fresh by SSE push (see server/sse.py),
      // not by polling -- refetchInterval is deliberately never set on any
      // query in this app. staleTime just avoids redundant refetches on
      // component remount for data that hasn't been invalidated.
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

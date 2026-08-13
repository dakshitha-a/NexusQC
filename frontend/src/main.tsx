import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import "./index.css";
import App from "./App.tsx";

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

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <App />
    </QueryClientProvider>
  </StrictMode>,
);

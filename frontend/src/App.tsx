import { PanelErrorBoundary } from "./app-shell/PanelErrorBoundary";
import { ShellLayout } from "./app-shell/ShellLayout";
import { AuthGate } from "./auth/AuthGate";

// AuthGate (and LoginScreen, which it renders while unauthenticated) sat
// outside every PanelErrorBoundary in the app -- every other boundary
// lives INSIDE ShellLayout, which AuthGate only mounts once a session is
// confirmed. A render-time exception here (not a handled fetch/HTTP
// error, which AuthGate's own useQuery branches already cover -- a genuine
// uncaught exception) took down the ENTIRE page with React's default
// unmount-the-whole-tree behavior and no recovery UI at all, confirmed via
// real browser testing. Wrapping here closes that gap the same way every
// other panel in this app already is.
function App() {
  return (
    <PanelErrorBoundary label="App">
      <AuthGate>
        <ShellLayout />
      </AuthGate>
    </PanelErrorBoundary>
  );
}

export default App;

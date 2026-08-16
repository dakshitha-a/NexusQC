import { ShellLayout } from "./app-shell/ShellLayout";
import { AuthGate } from "./auth/AuthGate";

function App() {
  return (
    <AuthGate>
      <ShellLayout />
    </AuthGate>
  );
}

export default App;

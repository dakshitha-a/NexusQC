import { Component, type ErrorInfo, type ReactNode } from "react";
import { AlertTriangle, RotateCcw } from "lucide-react";

interface Props {
  children: ReactNode;
  // Shown in the fallback ("This panel" by default) -- pass a specific
  // name (e.g. "Job details") so the user knows which part of the app hit
  // a problem, since several of these are mounted independently.
  label?: string;
}

interface State {
  error: Error | null;
}

// React unmounts the WHOLE tree on an uncaught render error by default --
// there was no error boundary anywhere in this app before this, so a
// single bad field in one job's summary/artifacts (or a malformed 3Dmol
// cube response, etc.) could blank the entire UI, not just the offending
// panel. Wrap each independent region of the shell (chat, job list, job
// detail drawer, KB pane) in its own instance so a crash in one doesn't
// take down the others -- and offer a reset that doesn't require a full
// page reload, since most of these failures are triggered by one specific
// piece of data, not a corrupted app state.
export class PanelErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error(`PanelErrorBoundary (${this.props.label ?? "panel"}) caught:`, error, info.componentStack);
  }

  render() {
    if (this.state.error) {
      return (
        <div className="flex flex-col items-center justify-center gap-2 p-4 text-center text-xs text-text-muted">
          <AlertTriangle size={18} className="text-amber-500" />
          <div>{this.props.label ?? "This panel"} hit an error and couldn't render.</div>
          <button
            onClick={() => this.setState({ error: null })}
            className="flex items-center gap-1 rounded border border-border px-2 py-1 hover:bg-surface-raised hover:text-text"
          >
            <RotateCcw size={12} />
            Try again
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}

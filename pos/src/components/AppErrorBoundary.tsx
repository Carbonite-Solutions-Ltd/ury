import { Component, type ErrorInfo, type ReactNode } from 'react';
import { AlertTriangle, RefreshCw, Copy } from 'lucide-react';

interface Props {
  children: ReactNode;
}

interface State {
  error: Error | null;
  componentStack: string | null;
  copied: boolean;
}

/**
 * Catches render-time crashes and shows what actually broke.
 *
 * WHY THIS EXISTS (2026-08-05). React 19 unmounts the ENTIRE tree when a
 * render throws and nothing catches it. With no boundary anywhere in the
 * POS, any such error produced a completely blank white page - no
 * message, no stack, nothing on screen at all. The only trace was a
 * console entry the cashier would never look at, and by the time it was
 * reported the useful detail was gone.
 *
 * That is not a hypothetical: a white /pos/orders was reported with a
 * fully-booted app behind it (profile, menu and session calls all
 * succeeding in the network log) and no way to see the cause.
 *
 * A boundary cannot prevent the bug, but it turns "the screen is white"
 * into a specific error message and stack the user can read out or copy,
 * which is the difference between a five-minute fix and an afternoon of
 * guessing.
 *
 * Deliberately a class component: `getDerivedStateFromError` /
 * `componentDidCatch` have no hook equivalent - this is the one place
 * React still requires a class.
 *
 * NOTE it does NOT catch errors thrown inside event handlers, promise
 * rejections, or async code - React boundaries never do. Those still
 * surface through the existing toast paths.
 */
class AppErrorBoundary extends Component<Props, State> {
  state: State = { error: null, componentStack: null, copied: false };

  static getDerivedStateFromError(error: Error): Partial<State> {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    // Keep the console record too - some deployments ship logs off-box.
    console.error('[URY] Uncaught render error:', error, info.componentStack);
    this.setState({ componentStack: info.componentStack ?? null });
  }

  private details(): string {
    const { error, componentStack } = this.state;
    return [
      `URY POS error: ${error?.name}: ${error?.message}`,
      `URL: ${window.location.href}`,
      `Time: ${new Date().toISOString()}`,
      '',
      error?.stack ?? '(no stack)',
      '',
      'Component stack:',
      componentStack ?? '(none)',
    ].join('\n');
  }

  private copy = () => {
    navigator.clipboard
      ?.writeText(this.details())
      .then(() => {
        this.setState({ copied: true });
        window.setTimeout(() => this.setState({ copied: false }), 2000);
      })
      .catch(() => {
        /* clipboard blocked - the text is on screen anyway */
      });
  };

  render() {
    const { error, componentStack, copied } = this.state;
    if (!error) return this.props.children;

    return (
      <div className="min-h-[100dvh] w-full overflow-y-auto bg-gray-50 p-4 sm:p-8">
        <div className="mx-auto max-w-2xl rounded-lg border border-red-200 bg-white shadow-sm">
          <div className="flex items-start gap-3 border-b border-gray-200 px-6 py-5">
            <AlertTriangle className="mt-0.5 h-6 w-6 shrink-0 text-red-600" />
            <div>
              <h1 className="text-lg font-semibold text-gray-900">
                Something broke while drawing this screen
              </h1>
              <p className="mt-1 text-sm text-gray-600">
                Your orders and payments are safe — this is a display fault,
                nothing was lost. Reload to carry on. If it keeps happening,
                send the details below.
              </p>
            </div>
          </div>

          <div className="px-6 py-4">
            <p className="text-sm font-semibold text-red-700 break-words">
              {error.name}: {error.message}
            </p>

            <pre className="mt-3 max-h-64 overflow-auto rounded bg-gray-900 p-3 text-xs leading-relaxed text-gray-100">
              {error.stack ?? '(no stack available)'}
              {componentStack ? `\n\nComponent stack:${componentStack}` : ''}
            </pre>
          </div>

          <div className="flex flex-wrap gap-2 border-t border-gray-200 px-6 py-4">
            <button
              onClick={() => window.location.reload()}
              className="inline-flex items-center gap-2 rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700"
            >
              <RefreshCw className="h-4 w-4" />
              Reload
            </button>
            <button
              onClick={this.copy}
              className="inline-flex items-center gap-2 rounded-lg border border-gray-300 px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50"
            >
              <Copy className="h-4 w-4" />
              {copied ? 'Copied' : 'Copy details'}
            </button>
          </div>
        </div>
      </div>
    );
  }
}

export default AppErrorBoundary;

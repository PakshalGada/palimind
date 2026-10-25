import { Component, type ErrorInfo, type ReactNode } from 'react';
import { AlertTriangle } from 'lucide-react';
import { Button, EmptyState } from '../ui/primitives';

interface Props {
  children: ReactNode;
}

interface State {
  error: Error | null;
}

/**
 * Last-resort boundary so a render error in one surface doesn't blank the
 * whole desktop app. The fallback offers an in-place retry and a full reload.
 */
export default class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    console.error('Uncaught render error:', error, info.componentStack);
  }

  private retry = () => {
    this.setState({ error: null });
  };

  private reload = () => {
    window.location.reload();
  };

  render() {
    const { error } = this.state;
    if (!error) return this.props.children;

    return (
      <div className="app-error-fallback" role="alert">
        <EmptyState
          icon={<AlertTriangle size={24} />}
          title="This view hit an unexpected error"
          description={error.message || 'The interface could not render this surface.'}
          action={
            <div className="app-error-fallback__actions">
              <Button variant="primary" size="sm" onClick={this.retry}>
                Try again
              </Button>
              <Button variant="secondary" size="sm" onClick={this.reload}>
                Reload app
              </Button>
            </div>
          }
        />
      </div>
    );
  }
}

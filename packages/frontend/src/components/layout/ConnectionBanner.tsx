import { useEffect, useState } from 'react';
import { AlertTriangle, X } from 'lucide-react';
import './ConnectionBanner.css';

interface ConnectionDetail {
  ok: boolean;
  message?: string;
}

/**
 * One quiet banner for backend/auth failures instead of a stack of identical
 * toasts. Any successful API response clears it.
 */
export default function ConnectionBanner() {
  const [message, setMessage] = useState<string | null>(null);
  const [details, setDetails] = useState(false);
  const [dismissed, setDismissed] = useState(false);

  useEffect(() => {
    const onConnection = (event: Event) => {
      const detail = (event as CustomEvent<ConnectionDetail>).detail;
      if (!detail) return;
      if (detail.ok) {
        setMessage(null);
        setDismissed(false);
        setDetails(false);
        return;
      }
      setDismissed(false);
      setMessage(detail.message || 'The local engine is not responding.');
    };
    window.addEventListener('palimind:connection', onConnection);
    return () => window.removeEventListener('palimind:connection', onConnection);
  }, []);

  if (!message || dismissed) return null;

  return (
    <div className="connection-banner" role="alert">
      <span className="connection-banner__icon" aria-hidden="true">
        <AlertTriangle size={15} />
      </span>
      <span className="connection-banner__text">
        <strong>Local engine not connected</strong>
        <span>{message}</span>
      </span>
      <button
        type="button"
        className="connection-banner__btn"
        onClick={() => window.location.reload()}
      >
        Retry
      </button>
      <button
        type="button"
        className="connection-banner__btn connection-banner__btn--ghost"
        aria-expanded={details}
        onClick={() => setDetails((value) => !value)}
      >
        {details ? 'Hide details' : 'Details'}
      </button>
      <button
        type="button"
        className="connection-banner__close"
        aria-label="Dismiss connection warning"
        onClick={() => setDismissed(true)}
      >
        <X size={14} />
      </button>
      {details && (
        <pre className="connection-banner__details">{message}</pre>
      )}
    </div>
  );
}

import { createContext, useCallback, useContext, useState, type ReactNode } from 'react';

interface ConfirmState {
  title?: string;
  message: string;
  confirmLabel?: string;
  cancelLabel?: string;
  danger?: boolean;
  resolve: (v: boolean) => void;
}

type ConfirmFn = (message: string, opts?: Omit<ConfirmState, 'message' | 'resolve'>) => Promise<boolean>;

const ConfirmContext = createContext<ConfirmFn>(() => Promise.resolve(false));

export function useConfirm(): ConfirmFn {
  return useContext(ConfirmContext);
}

export function ConfirmProvider({ children }: { children: ReactNode }) {
  const [pending, setPending] = useState<ConfirmState | null>(null);

  const confirm = useCallback<ConfirmFn>((message, opts) => {
    return new Promise<boolean>((resolve) => {
      setPending({ message, ...opts, resolve });
    });
  }, []);

  const close = (result: boolean) => {
    pending?.resolve(result);
    setPending(null);
  };

  return (
    <ConfirmContext.Provider value={confirm}>
      {children}
      {pending && (
        <div className="confirm-overlay" onClick={() => close(false)}>
          <div className="confirm-dialog" onClick={(e) => e.stopPropagation()}>
            {pending.title && <h3 className="confirm-title">{pending.title}</h3>}
            <p className="confirm-message">{pending.message}</p>
            <div className="confirm-actions">
              <button className="action-btn ghost" onClick={() => close(false)} autoFocus>
                {pending.cancelLabel || 'Cancel'}
              </button>
              <button
                className={`action-btn primary${pending.danger ? ' danger-btn' : ''}`}
                onClick={() => close(true)}
              >
                {pending.confirmLabel || 'Confirm'}
              </button>
            </div>
          </div>
        </div>
      )}
    </ConfirmContext.Provider>
  );
}
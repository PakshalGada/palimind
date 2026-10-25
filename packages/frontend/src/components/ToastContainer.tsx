import { useApp } from '../AppContext';
import { Toast } from '../ui/primitives';

export default function ToastContainer() {
  const { toasts, dismissToast } = useApp();

  if (toasts.length === 0) return null;

  return (
    <div className="ui-toast-viewport" aria-live="polite" aria-label="Notifications">
      {toasts.map(toast => (
        <Toast
          key={toast.id}
          title={toast.title}
          message={toast.message}
          tone={toast.tone}
          action={toast.action}
          duration={toast.duration}
          onDismiss={() => dismissToast(toast.id)}
        />
      ))}
    </div>
  );
}

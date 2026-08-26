import { useApp } from '../AppContext';

export default function ToastContainer() {
  const { toasts } = useApp();

  return (
    <>
      {toasts.map(toast => (
        <div key={toast.id} className="sync-toast">
          {toast.message}
        </div>
      ))}
    </>
  );
}

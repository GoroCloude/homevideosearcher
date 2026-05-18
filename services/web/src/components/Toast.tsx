import { useState, useEffect } from 'react';
import clsx from 'clsx';
import { type Toast, useToastSubscription, unsubscribeToast, removeToast } from '../hooks/useToast';

const TYPE_CLASSES: Record<Toast['type'], string> = {
  success: 'bg-green-700 text-white',
  error:   'bg-red-700 text-white',
  info:    'bg-gray-800 text-white',
};

const TYPE_ICON: Record<Toast['type'], string> = {
  success: '✓',
  error:   '✕',
  info:    'ℹ',
};

export default function ToastContainer() {
  const [toasts, setToasts] = useState<Toast[]>([]);

  useEffect(() => {
    const listener = (updated: Toast[]) => setToasts(updated);
    useToastSubscription(listener);
    return () => unsubscribeToast(listener);
  }, []);

  if (toasts.length === 0) return null;

  return (
    <div
      aria-live="polite"
      aria-atomic="false"
      className="fixed bottom-20 sm:bottom-4 right-4 z-50 flex flex-col gap-2 max-w-xs w-full pointer-events-none"
    >
      {toasts.map(toast => (
        <div
          key={toast.id}
          role="alert"
          className={clsx(
            'flex items-start gap-2 px-3 py-2.5 rounded-lg shadow-lg pointer-events-auto',
            'transition-transform duration-200',
            TYPE_CLASSES[toast.type],
          )}
        >
          <span className="text-sm font-bold mt-0.5 shrink-0">{TYPE_ICON[toast.type]}</span>
          <span className="text-sm flex-1 leading-snug">{toast.message}</span>
          <button
            onClick={() => removeToast(toast.id)}
            className="text-white/70 hover:text-white text-lg leading-none shrink-0 ml-1"
            aria-label="Dismiss notification"
          >
            ×
          </button>
        </div>
      ))}
    </div>
  );
}

// Module-level state (singleton — works across the entire app)
export type ToastType = 'success' | 'error' | 'info';

export interface Toast {
  id:      string;
  message: string;
  type:    ToastType;
}

type Listener = (toasts: Toast[]) => void;

let toasts:    Toast[]    = [];
let listeners: Listener[] = [];

function notify() {
  listeners.forEach(fn => fn([...toasts]));
}

/** Call from anywhere — no hook required. */
export function addToast(message: string, type: ToastType = 'info', durationMs = 4000): void {
  const id = `toast-${Date.now()}-${Math.random().toString(36).slice(2)}`;
  toasts = [...toasts, { id, message, type }];
  notify();
  setTimeout(() => {
    toasts = toasts.filter(t => t.id !== id);
    notify();
  }, durationMs);
}

export function removeToast(id: string): void {
  toasts = toasts.filter(t => t.id !== id);
  notify();
}

/** React hook — used only by ToastContainer to subscribe. */
export function useToastSubscription(listener: Listener): void {
  // Called once on ToastContainer mount; cleaned up on unmount
  if (!listeners.includes(listener)) {
    listeners.push(listener);
  }
  // Cleanup is handled by caller (useEffect return)
}

export function unsubscribeToast(listener: Listener): void {
  listeners = listeners.filter(fn => fn !== listener);
}

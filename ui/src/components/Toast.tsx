// ARCEN — Toast: transient bottom-right confirmation (T-036).
// "Saved" or "Error: <reason>" — auto-dismisses, respects reduced motion.

import { useEffect } from 'react';

export function Toast({ message, kind, onDone }: { message: string; kind: 'ok' | 'err'; onDone: () => void }) {
  useEffect(() => {
    const t = window.setTimeout(onDone, 3200);
    return () => window.clearTimeout(t);
  }, [message, onDone]);

  return (
    <div className={`toast ${kind === 'err' ? 'toast-err' : ''}`} role="status" data-testid="toast">
      {message}
    </div>
  );
}

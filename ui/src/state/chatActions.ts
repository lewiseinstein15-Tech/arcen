// ARCEN — chat-level actions shared by the sidebar and the top bar (T-035).
// "+ New chat": save the current session to history (it stays on the server
// and in the sessions drawer), switch to a fresh session id, clear the
// stream, and focus the composer. A session with 0 messages is NOT replaced
// — no churn on an untouched chat.

import { useSessionStore } from './sessionStore';
import { useStreamStore } from './streamStore';

export const FOCUS_COMPOSER_EVENT = 'arcen:focus-composer';

export function focusComposer(): void {
  // deferred: the fresh Composer mounts after the session swap commits —
  // a synchronous dispatch would be caught by the dying instance
  window.setTimeout(() => window.dispatchEvent(new CustomEvent(FOCUS_COMPOSER_EVENT)), 0);
}

export function newChat(): void {
  const { events } = useStreamStore.getState();
  if (events.length === 0) {
    // the current chat has nothing to save — keep the same session
    focusComposer();
    return;
  }
  const fresh = crypto.randomUUID();
  useSessionStore.getState().open(fresh); // the old session stays in the drawer (server history)
  useStreamStore.getState().reset(); // clear the stream for the fresh chat
  focusComposer();
}

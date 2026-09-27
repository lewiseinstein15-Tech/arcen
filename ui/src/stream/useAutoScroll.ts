// ARCEN — auto-scroll (FRONTEND-SPEC Part 6). BOTTOM_THRESHOLD = 100, frozen.
// While pinned, every appended event scrolls to bottom (no smooth animation).
// While browsing, nothing moves — the stream never yanks the reader.

import { useCallback, useEffect, useRef } from 'react';

export const BOTTOM_THRESHOLD = 100; // px from bottom that still counts as "pinned"

export interface ScrollTracker {
  pinned: boolean;
  pendingCount: number;
  /** Feed the current distance-from-bottom (px) on scroll. */
  onScroll: (distanceFromBottom: number) => void;
  /** Called when a new event appends. Returns true if the view should follow. */
  onAppend: () => boolean;
  scrollToBottom: () => void;
}

export function createScrollTracker(threshold: number = BOTTOM_THRESHOLD): ScrollTracker {
  const state = { pinned: true, pending: 0 };
  return {
    get pinned() {
      return state.pinned;
    },
    get pendingCount() {
      return state.pending;
    },
    onScroll(distanceFromBottom: number) {
      state.pinned = distanceFromBottom <= threshold;
      if (state.pinned) state.pending = 0;
    },
    onAppend() {
      if (state.pinned) return true;
      state.pending += 1;
      return false;
    },
    scrollToBottom() {
      state.pinned = true;
      state.pending = 0;
    },
  };
}

export function useAutoScroll(dep: unknown) {
  const ref = useRef<HTMLDivElement>(null);
  const tracker = useRef<ScrollTracker>(createScrollTracker());

  const onScroll = useCallback(() => {
    const el = ref.current;
    if (!el) return;
    tracker.current.onScroll(el.scrollHeight - el.scrollTop - el.clientHeight);
  }, []);

  useEffect(() => {
    const el = ref.current;
    const follow = tracker.current.onAppend();
    if (el && follow) el.scrollTop = el.scrollHeight; // follow the stream
  }, [dep]);

  const scrollToBottom = useCallback(() => {
    const el = ref.current;
    if (el) el.scrollTop = el.scrollHeight;
    tracker.current.scrollToBottom();
  }, []);

  return { ref, onScroll, pinned: tracker.current.pinned, pendingCount: tracker.current.pendingCount, scrollToBottom };
}

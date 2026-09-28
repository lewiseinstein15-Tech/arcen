// ARCEN — auto-scroll (FRONTEND-SPEC Part 6). BOTTOM_THRESHOLD = 100, frozen.
//
// T-034 makes the hook actually work in ChatView (it existed but was never
// mounted). The core insight: every scroll-source movement is monotone.
// Content growth and programmatic catch-up both push scrollTop DOWN toward
// the bottom — only a real user can move it UP. So:
//   * scrollTop decreasing  → the user scrolled up: unpin when >100px away
//   * distance <= 100px     → in the bottom strip: pinned, whatever the cause
//   * everything else       → growth / catch-up mid-flight: never yank
// No settle timers needed — the rule is direction-based and self-stabilizing.

import { useCallback, useEffect, useRef, useState } from 'react';

export const BOTTOM_THRESHOLD = 100; // px from bottom that still counts as "pinned"

export interface ScrollTracker {
  pinned: boolean;
  pendingCount: number;
  /** Feed the current distance-from-bottom (px) on a user scroll. */
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
  const prev = useRef<{ top: number; height: number } | null>(null);
  const [ui, setUi] = useState({ pinned: true, pending: 0 });

  const sync = useCallback(() => {
    setUi({ pinned: tracker.current.pinned, pending: tracker.current.pendingCount });
  }, []);

  const onScroll = useCallback(() => {
    const el = ref.current;
    if (!el) return;
    const dist = el.scrollHeight - el.scrollTop - el.clientHeight;
    const p = prev.current;
    prev.current = { top: el.scrollTop, height: el.scrollHeight };
    if (p && el.scrollTop - p.top < -2) {
      tracker.current.onScroll(dist); // upward movement → possible unpin
    }
    if (dist <= BOTTOM_THRESHOLD) {
      tracker.current.onScroll(dist); // bottom strip → pinned (F-06 threshold)
    }
    sync();
  }, [sync]);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    if (tracker.current.onAppend()) {
      // instant follow (Part 6: streaming appends never animate — a smooth
      // animation per event lags the stream and reads as unpinned); the
      // smooth behavior is reserved for the pill jump below
      el.scrollTop = el.scrollHeight;
    }
  }, [dep]);

  const scrollToBottom = useCallback(() => {
    const el = ref.current;
    tracker.current.scrollToBottom(); // re-pin: pill click contract (F-08)
    if (el) el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' });
    sync();
  }, [sync]);

  return { ref, onScroll, pinned: ui.pinned, pendingCount: ui.pending, scrollToBottom };
}

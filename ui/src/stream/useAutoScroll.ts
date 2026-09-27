// ARCEN — auto-scroll (FRONTEND-SPEC Part 6). BOTTOM_THRESHOLD = 100, frozen.

import { useCallback, useEffect, useRef } from 'react';

const BOTTOM_THRESHOLD = 100; // px from bottom that still counts as "pinned"

export function useAutoScroll(dep: unknown) {
  const ref = useRef<HTMLDivElement>(null);
  const pinned = useRef(true);
  const pending = useRef(0); // events appended since the user left the bottom

  const onScroll = useCallback(() => {
    const el = ref.current;
    if (!el) return;
    pinned.current = el.scrollHeight - el.scrollTop - el.clientHeight <= BOTTOM_THRESHOLD;
    if (pinned.current) pending.current = 0;
  }, []);

  useEffect(() => {
    const el = ref.current;
    if (el && pinned.current) el.scrollTop = el.scrollHeight; // follow the stream
    else pending.current += 1; // browsing: count, never yank
  }, [dep]);

  const scrollToBottom = useCallback(() => {
    const el = ref.current;
    if (!el) return;
    el.scrollTop = el.scrollHeight;
    pinned.current = true;
    pending.current = 0;
  }, []);

  return { ref, onScroll, pinned: pinned.current, pendingCount: pending.current, scrollToBottom };
}

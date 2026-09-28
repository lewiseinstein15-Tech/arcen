// ARCEN — stream store: events ordered by seq + the growing draft.
// (FRONTEND-SPEC Part 8/9: events[], status, lastSeq, apply, hydrate.)
//
// T-032 live visibility:
// - pendingTurn: the optimistic user message set the instant Send is
//   pressed, cleared the moment the server's run.start lands (server
//   truth takes over — no double pill).
// - events are kept strictly seq-ordered on insert: an event that races
//   ahead of its predecessor slots into its seq position, so a partial
//   turn can never render out of order (Part 7). Gaps self-heal — when
//   the missing seq arrives it is inserted where it belongs.

import { create } from 'zustand';
import type { ArcenEvent } from '../types/events';

export type StreamStatus = 'idle' | 'streaming' | 'done' | 'error';

export interface PendingTurn {
  text: string;
  at: number;
}

interface StreamStore {
  events: ArcenEvent[];
  status: StreamStatus;
  lastSeq: number;
  pendingTurn: PendingTurn | null;
  apply: (e: ArcenEvent) => void;
  hydrate: (events: ArcenEvent[]) => void;
  reset: () => void;
  setPendingTurn: (text: string) => void;
  clearPendingTurn: () => void;
}

function statusFor(e: ArcenEvent): StreamStatus {
  return e.type === 'run.done' || e.type === 'run.error' ? 'done' : 'streaming';
}

export const useStreamStore = create<StreamStore>((set) => ({
  events: [],
  status: 'idle',
  lastSeq: 0,
  pendingTurn: null,
  apply: (e) =>
    set((s) => {
      if ((e as { type?: string }).type === 'stream.done') {
        // transport frame (not one of the 17 events) — the server closed
        // the stream cleanly after a terminal event
        return { status: 'done' };
      }
      if (typeof e.seq !== 'number' || e.seq <= s.lastSeq) return s; // duplicates dropped (Part 7)
      if (s.events.some((x) => x.seq === e.seq)) return s; // already buffered past a gap
      const insertAt = s.events.findIndex((seen) => seen.seq > e.seq);
      const events =
        insertAt === -1 ? [...s.events, e] : [...s.events.slice(0, insertAt), e, ...s.events.slice(insertAt)];
      const next: Partial<StreamStore> = { events, status: statusFor(e) };
      if (e.type === 'run.start') next.pendingTurn = null; // server truth arrived
      if (e.seq === s.lastSeq + 1) {
        // contiguous with what the user has seen — advance the frontier
        // over any run of already-buffered events this unblocks
        let frontier = e.seq;
        while (events.some((x) => x.seq === frontier + 1)) frontier += 1;
        next.lastSeq = frontier;
      }
      // a gap arrival slots into place without advancing the frontier —
      // the render position is still correct (sorted), nothing drops
      return next;
    }),
  hydrate: (events) =>
    set({
      events: [...events].sort((a, b) => a.seq - b.seq), // defensive: replay must be ascending (T-033)
      lastSeq: events.length ? Math.max(...events.map((e) => e.seq)) : 0,
      status: events.length ? 'done' : 'idle',
      pendingTurn: null,
    }),
  reset: () => set({ events: [], status: 'idle', lastSeq: 0, pendingTurn: null }),
  setPendingTurn: (text) => set({ pendingTurn: { text, at: Date.now() } }),
  clearPendingTurn: () => set({ pendingTurn: null }),
}));

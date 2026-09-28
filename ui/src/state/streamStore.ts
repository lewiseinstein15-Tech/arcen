// ARCEN — stream store: events ordered by seq + the growing draft.
// (FRONTEND-SPEC Part 8/9: events[], status, lastSeq, apply, hydrate.)

import { create } from 'zustand';
import type { ArcenEvent } from '../types/events';

export type StreamStatus = 'idle' | 'streaming' | 'done' | 'error';

interface StreamStore {
  events: ArcenEvent[];
  status: StreamStatus;
  lastSeq: number;
  apply: (e: ArcenEvent) => void;
  hydrate: (events: ArcenEvent[]) => void;
  reset: () => void;
}

export const useStreamStore = create<StreamStore>((set) => ({
  events: [],
  status: 'idle',
  lastSeq: 0,
  apply: (e) =>
    set((s) => {
      if ((e as { type?: string }).type === 'stream.done') {
        // transport frame (not one of the 17 events) — the server closed
        // the stream cleanly after a terminal event
        return { status: 'done' };
      }
      if (typeof e.seq !== 'number' || e.seq <= s.lastSeq) return s; // duplicates dropped (Part 7)
      const status: StreamStatus =
        e.type === 'run.done' || e.type === 'run.error' ? 'done' : 'streaming';
      return { events: [...s.events, e], lastSeq: e.seq, status };
    }),
  hydrate: (events) =>
    set({
      events,
      lastSeq: events.length ? events[events.length - 1].seq : 0,
      status: events.length ? 'done' : 'idle',
    }),
  reset: () => set({ events: [], status: 'idle', lastSeq: 0 }),
}));

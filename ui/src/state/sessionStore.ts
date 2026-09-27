// ARCEN — session store (FRONTEND-SPEC Part 8).
// The UI never touches jsonl/SQLite — only the API.

import { create } from 'zustand';
import type { ArcenEvent } from '../types/events';

export interface SessionMeta {
  id: string;
  title: string;
  status: string;
  events: number;
  last_seq: number;
  created_at: number;
}

interface SessionStore {
  sessions: SessionMeta[];
  activeId: string | null;
  list: () => Promise<void>;
  open: (id: string) => void;
  replay: (id: string) => Promise<ArcenEvent[]>;
}

export const useSessionStore = create<SessionStore>((set) => ({
  sessions: [],
  activeId: null,
  list: async () => {
    try {
      const res = await fetch('/api/sessions');
      if (res.ok) set({ sessions: (await res.json()) as SessionMeta[] });
    } catch {
      // offline / mid-reload: keep the previous list, never crash the UI
    }
  },
  open: (id) => {
    set({ activeId: id });
    localStorage.setItem('arcen.activeId', id); // Part 8: active session id
  },
  replay: async (id) => {
    const res = await fetch(`/api/sessions/${id}/events`);
    if (!res.ok) return [];
    return (await res.json()) as ArcenEvent[];
  },
}));

// localStorage persistence of the active id (Part 8)
export function restoreActiveId(): string | null {
  return localStorage.getItem('arcen.activeId');
}

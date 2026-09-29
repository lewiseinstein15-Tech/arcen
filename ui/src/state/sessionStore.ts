// ARCEN — session store (FRONTEND-SPEC Part 8).
// The UI never touches jsonl/SQLite — only the API.
//
// T-045: session ids are generated per browser context. There is no
// hardcoded default id: a fresh context (nothing stored) gets a fresh
// crypto.randomUUID() BEFORE the first render can touch the wire, so
// every user's first session is unique — ids never collide across
// users/machines, old events never leak into new sessions, and the
// drawer never merges strangers into one giant session. The historic
// id 's-ui' survives only as a migration target (rotateLegacySession).

import { create } from 'zustand';
import type { ArcenEvent } from '../types/events';

/**
 * The pre-T-045 hardcoded default. It is no longer a default — it exists
 * so an old browser context can replay its history once and then rotate
 * to a generated id. Never write this value into localStorage again.
 */
export const LEGACY_SESSION_ID = 's-ui';

export function newSessionId(): string {
  return crypto.randomUUID();
}

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

/**
 * T-045 boot resolution. Reads the stored session id; a fresh browser
 * context (nothing stored — or a legacy empty string) generates a UUID
 * and persists it BEFORE any request can carry a session. Every call
 * site therefore sees a per-context id, never a shared constant.
 */
export function resolveInitialSessionId(): string {
  const stored = localStorage.getItem('arcen.activeId');
  if (stored !== null && stored !== '') return stored;
  const fresh = newSessionId();
  localStorage.setItem('arcen.activeId', fresh);
  return fresh;
}

/**
 * Seed the store once per load. Idempotent (guarded by activeId), so
 * App can call it during the first render and StrictMode double-renders
 * converge on the same id instead of minting two.
 */
export function ensureActiveSession(): string {
  const existing = useSessionStore.getState().activeId;
  if (existing !== null) return existing;
  const id = resolveInitialSessionId();
  useSessionStore.setState({ activeId: id });
  return id;
}

/**
 * T-045 legacy migration. A context still pinned to 's-ui' loads its old
 * events ONCE (ChatView replays them), then rotates: a fresh UUID is
 * generated, persisted, and made active — the next turn runs on it, and
 * 's-ui' stays on the server/drawer as history. No-op for every other id.
 */
export function rotateLegacySession(id: string): string {
  if (id !== LEGACY_SESSION_ID) return id;
  const fresh = newSessionId();
  localStorage.setItem('arcen.activeId', fresh);
  useSessionStore.setState({ activeId: fresh });
  return fresh;
}

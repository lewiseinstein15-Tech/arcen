// ARCEN — localStorage persistence (FRONTEND-SPEC Part 8).
// Keys: arcen.activeId · arcen.draft · arcen.lastSeq · arcen.panels
// The UI never touches jsonl/SQLite — only the API + these keys.

const KEYS = {
  activeId: 'arcen.activeId',
  draft: 'arcen.draft',
  lastSeq: 'arcen.lastSeq',
} as const;

export function loadActiveId(): string | null {
  return localStorage.getItem(KEYS.activeId);
}

export function saveActiveId(id: string | null): void {
  if (id === null) localStorage.removeItem(KEYS.activeId);
  else localStorage.setItem(KEYS.activeId, id);
}

export function loadDraft(): string {
  return localStorage.getItem(KEYS.draft) ?? '';
}

export function saveDraft(draft: string): void {
  if (draft === '') localStorage.removeItem(KEYS.draft);
  else localStorage.setItem(KEYS.draft, draft);
}

export function loadLastSeq(sessionId: string): number {
  const raw = localStorage.getItem(`${KEYS.lastSeq}:${sessionId}`);
  const n = raw === null ? 0 : Number(raw);
  return Number.isFinite(n) ? n : 0;
}

export function saveLastSeq(sessionId: string, seq: number): void {
  localStorage.setItem(`${KEYS.lastSeq}:${sessionId}`, String(seq));
}

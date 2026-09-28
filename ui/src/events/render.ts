// ARCEN — render rules (FRONTEND-SPEC Part 3): glyph map, colors, indent.
// Module-level constants, computed once (Part 12 memoization table).

export interface BlockStyle {
  glyph: string;
  color: string; // a CSS custom property name
}

export const GLYPHS: Record<string, BlockStyle> = {
  'run.start': { glyph: '◆', color: 'var(--accent)' },
  'run.done': { glyph: '◇', color: 'var(--success)' },
  'run.error': { glyph: '✗', color: 'var(--danger)' },
  'step.fail': { glyph: '✗', color: 'var(--danger)' },
  think: { glyph: '✱', color: 'var(--text-3)' },
  plan: { glyph: '▸', color: 'var(--accent)' },
  'plan.update': { glyph: '↻', color: 'var(--warn)' },
  spawn: { glyph: '⎇', color: 'var(--info)' },
  'spawn.done': { glyph: '✓', color: 'var(--success)' },
  command: { glyph: '❯', color: 'var(--accent)' },
  'command.done': { glyph: '●', color: 'var(--success)' },
  'file.diff': { glyph: 'Δ', color: 'var(--info)' },
  'verify.start': { glyph: '⊙', color: 'var(--memory)' },
  'step.pass': { glyph: '⚑', color: 'var(--success)' },
  answer: { glyph: '✦', color: 'var(--accent-hi)' },
  memory: { glyph: '⬡', color: 'var(--memory)' },
  usage: { glyph: '¤', color: 'var(--text-2)' },
};

// default panel state per event (Part 2). plan.update mutates PlanBlock in
// place; command.done mutates its CommandBlock; spawn.done its SpawnBlock.
export const DEFAULT_STATE: Record<string, 'open' | 'collapsed'> = {
  'run.start': 'collapsed', // the goal line is always visible anyway
  think: 'collapsed',
  plan: 'open',
  'plan.update': 'open',
  spawn: 'open',
  'spawn.done': 'collapsed',
  command: 'open',
  'command.done': 'collapsed',
  'file.diff': 'collapsed',
  'verify.start': 'open',
  'step.pass': 'collapsed',
  'step.fail': 'open',
  answer: 'open', // never collapsed
  memory: 'collapsed',
  usage: 'collapsed',
  'run.done': 'collapsed',
  'run.error': 'open',
};

// user overrides win over defaults for the session (Part 4)

// 2 spaces per depth level, cap at 3 (max 6 spaces) — Part 3.4
export function indent(depth: number): number {
  return Math.min(depth, 3) * 2;
}

export function truncate(text: string, n: number): string {
  return text.length > n ? text.slice(0, n - 1) + '…' : text;
}

// unix seconds → HH:MM (local, 24h) — the message timestamp under
// user pills and bot messages (reference brief)
export function fmtTime(ts: number | undefined): string {
  if (typeof ts !== 'number' || !Number.isFinite(ts)) return '';
  const d = new Date(ts * 1000);
  if (Number.isNaN(d.getTime())) return '';
  const hh = String(d.getHours()).padStart(2, '0');
  const mm = String(d.getMinutes()).padStart(2, '0');
  return `${hh}:${mm}`;
}

export function summarizeArgs(args: Record<string, unknown>): string {
  const parts = Object.entries(args).map(([k, v]) => {
    const s = typeof v === 'string' ? v : JSON.stringify(v);
    return `${k}=${truncate(s, 60)}`;
  });
  return truncate(parts.join(' '), 80);
}

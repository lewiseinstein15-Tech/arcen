// ARCEN — panel state machine (FRONTEND-SPEC Part 4, frozen transitions).

import { create } from 'zustand';

export type PanelState = 'open' | 'closed' | 'auto';
export type BlockKind =
  | 'think'
  | 'plan'
  | 'spawn'
  | 'command'
  | 'diff'
  | 'verify'
  | 'memory'
  | 'error';

export const BLOCK_KINDS: BlockKind[] = [
  'think',
  'plan',
  'spawn',
  'command',
  'diff',
  'verify',
  'memory',
  'error',
];

// high-signal events reopen a closed panel (Part 4)
export const HIGH_SIGNAL: BlockKind[] = ['plan', 'verify', 'error'];

export function kindFor(eventType: string): BlockKind | null {
  switch (eventType) {
    case 'think':
      return 'think';
    case 'plan':
    case 'plan.update':
      return 'plan';
    case 'spawn':
    case 'spawn.done':
      return 'spawn';
    case 'command':
    case 'command.done':
      return 'command';
    case 'file.diff':
      return 'diff';
    case 'verify.start':
    case 'step.pass':
    case 'step.fail':
      return 'verify';
    case 'memory':
      return 'memory';
    case 'run.error':
      return 'error';
    default:
      return null; // run.start / answer / usage / run.done never panel
  }
}

interface PanelStore {
  panels: Record<BlockKind, PanelState>;
  badges: Record<BlockKind, number>;
  set: (kind: BlockKind, state: PanelState) => void;
  toggle: (kind: BlockKind) => void;
  onEvent: (kind: BlockKind) => void;
  reset: () => void;
}

const initialPanels = Object.fromEntries(BLOCK_KINDS.map((k) => [k, 'auto'])) as Record<
  BlockKind,
  PanelState
>;
const initialBadges = Object.fromEntries(BLOCK_KINDS.map((k) => [k, 0])) as Record<
  BlockKind,
  number
>;

export const usePanelStore = create<PanelStore>((set) => ({
  panels: initialPanels,
  badges: initialBadges,
  set: (kind, state) => set((s) => ({ panels: { ...s.panels, [kind]: state } })),
  toggle: (kind) =>
    set((s) => ({
      panels: {
        ...s.panels,
        [kind]:
          s.panels[kind] === 'open' || s.panels[kind] === 'auto' ? 'closed' : 'open',
      },
    })),
  onEvent: (kind) =>
    set((s) => {
      const state = s.panels[kind];
      if (state !== 'closed') return {}; // auto/open: default wins
      if (HIGH_SIGNAL.includes(kind)) return { panels: { ...s.panels, [kind]: 'open' } };
      return { badges: { ...s.badges, [kind]: s.badges[kind] + 1 } };
    }),
  reset: () => set({ panels: initialPanels, badges: initialBadges }),
}));

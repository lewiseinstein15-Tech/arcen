// F-05 — panel machine: chevron toggles auto→open→closed; closed + low-signal
// → badge count; closed + high-signal (plan / step.fail / run.error) → opens.

import { beforeEach, describe, expect, it } from 'vitest';
import { BLOCK_KINDS, usePanelStore } from '../src/state/panelStore';

function reset() {
  usePanelStore.getState().reset();
}

beforeEach(reset);

describe('F-05: panel state machine', () => {
  it('chevron cycles auto → open → closed → open', () => {
    const { toggle } = usePanelStore.getState();
    expect(usePanelStore.getState().panels.command).toBe('auto');
    toggle('command');
    expect(usePanelStore.getState().panels.command).toBe('open'); // pinned open
    toggle('command');
    expect(usePanelStore.getState().panels.command).toBe('closed'); // unpin → closed
    toggle('command');
    expect(usePanelStore.getState().panels.command).toBe('open');
  });

  it('closed + low-signal event increments the badge, panel stays closed', () => {
    const store = usePanelStore.getState();
    store.set('command', 'closed');
    store.onEvent('command');
    store.onEvent('command');
    const s1 = usePanelStore.getState();
    expect(s1.panels.command).toBe('closed');
    expect(s1.badges.command).toBe(2);
    // while open, no badge accrues — the default wins
    s1.toggle('command'); // closed → open
    s1.onEvent('command');
    expect(usePanelStore.getState().badges.command).toBe(2);
  });

  it('closed + high-signal event reopens the panel (plan / verify / error)', () => {
    const { set, toggle } = usePanelStore.getState();
    for (const kind of ['plan', 'verify', 'error'] as const) {
      set(kind, 'closed');
      usePanelStore.getState().onEvent(kind); // high-signal arrives
      const s = usePanelStore.getState();
      expect(s.panels[kind]).toBe('open');
      expect(s.badges[kind]).toBe(0); // reopened, not counted
    }
    // silence the unused vars for lint
    void toggle;
  });

  it('all 8 block kinds participate', () => {
    expect(BLOCK_KINDS).toHaveLength(8);
    for (const kind of BLOCK_KINDS) {
      expect(usePanelStore.getState().panels[kind]).toBe('auto');
      usePanelStore.getState().set(kind, 'closed');
      expect(usePanelStore.getState().panels[kind]).toBe('closed');
    }
  });

  it('reset returns to defaults (session replay, Part 4)', () => {
    const { set } = usePanelStore.getState();
    set('think', 'closed');
    usePanelStore.getState().reset();
    expect(usePanelStore.getState().panels.think).toBe('auto');
    expect(usePanelStore.getState().badges.think).toBe(0);
  });
});

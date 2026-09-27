// F-12 — reload mid-session: replay restores events in seq order; composer
// draft restored from localStorage (FRONTEND-SPEC Part 8).

import { render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ChatView } from '../src/components/ChatView';
import { useStreamStore } from '../src/state/streamStore';
import { loadDraft, saveActiveId, saveDraft, saveLastSeq } from '../src/state/persist';
import { foldEvents } from '../src/stream/fold';
import type { ArcenEvent } from '../src/types/events';

const SESSION = 's-reload-test';

const EVENTS: ArcenEvent[] = [
  { type: 'run.start', seq: 1, ts: 1727500000.0, run_id: 'r-01J9', goal: 'fix the failing test', depth: 0 },
  { type: 'think', seq: 2, ts: 1727500000.1, agent: 'DRAFT', text: 'Read the test first.' },
  {
    type: 'plan',
    seq: 3,
    ts: 1727500000.2,
    agent: 'DRAFT',
    steps: [{ id: 1, title: 'read failing test', tool: 'file.read' }],
  },
  { type: 'command', seq: 4, ts: 1727500000.3, agent: 'FORGE', step: 1, tool: 'file.read', args: { path: 't.py' } },
  {
    type: 'command.done',
    seq: 5,
    ts: 1727500000.4,
    step: 1,
    ok: true,
    result: { content: 'x' },
    duration_s: 0.01,
  },
  { type: 'answer', seq: 6, ts: 1727500000.5, text: 'Fixed.' },
];

beforeEach(() => {
  localStorage.clear();
  useStreamStore.getState().reset();
});

describe('F-12: reload mid-session', () => {
  it('localStorage arcen.* keys round-trip', () => {
    saveActiveId(SESSION);
    saveDraft('my unsent draft');
    saveLastSeq(SESSION, 42);
    expect(loadDraft()).toBe('my unsent draft');
    expect(localStorage.getItem('arcen.activeId')).toBe(SESSION);
    expect(localStorage.getItem(`arcen.lastSeq:${SESSION}`)).toBe('42');
  });

  it('replay via the API hydrates the stream in seq order', async () => {
    const fetchMock = vi.fn().mockImplementation((url: string) => {
      if (String(url).includes('/api/sessions/')) {
        return Promise.resolve(new Response(JSON.stringify(EVENTS), { status: 200 }));
      }
      // the live stream: no further events
      return Promise.resolve(new Response('', { status: 200 }));
    });
    vi.stubGlobal('fetch', fetchMock);

    render(<ChatView sessionId={SESSION} />);

    await waitFor(() => {
      expect(useStreamStore.getState().events).toHaveLength(EVENTS.length);
    });
    const seqs = useStreamStore.getState().events.map((e) => e.seq);
    expect(seqs).toEqual([1, 2, 3, 4, 5, 6]);
    // blocks render in order
    expect(document.querySelector('[data-seq="1"]')).not.toBeNull();
    expect(document.querySelector('[data-seq="6"]')).not.toBeNull();
    // plan folds its command pair
    const folded = foldEvents(useStreamStore.getState().events);
    expect(folded.find((b) => b.primary.type === 'command')?.done?.seq).toBe(5);
  });

  it('composer draft is restored from localStorage after reload', async () => {
    saveDraft('continue with the migration');
    render(<ChatView sessionId={SESSION} />);
    await waitFor(() => {
      const input = document.querySelector('[data-testid="composer-input"]') as HTMLTextAreaElement;
      expect(input.value).toBe('continue with the migration');
    });
  });

  it('draft edits persist to localStorage as they change', async () => {
    render(<ChatView sessionId={SESSION} />);
    const input = document.querySelector('[data-testid="composer-input"]') as HTMLTextAreaElement;
    // simulate typing through the store-driven value change
    input.focus();
    // ChatView controls the value; dispatch a change via the native setter
    const setter = Object.getOwnPropertyDescriptor(
      window.HTMLTextAreaElement.prototype,
      'value',
    )?.set;
    setter?.call(input, 'typed mid-flight');
    input.dispatchEvent(new Event('change', { bubbles: true }));
    await waitFor(() => {
      expect(loadDraft()).toBe('typed mid-flight');
    });
  });
});

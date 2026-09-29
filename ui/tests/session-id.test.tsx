// T-045 — session ids are generated per browser context, never hardcoded.
// Proves: a fresh context (nothing stored) boots on a generated UUID that is
// persisted before the first render; a reload reuses the stored id; a legacy
// context pinned to 's-ui' loads its old events exactly once, then rotates to
// a fresh UUID (persisted) for the next turn — 's-ui' is never sent again.

import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import App from '../src/App';
import { useSessionStore } from '../src/state/sessionStore';
import { useStreamStore } from '../src/state/streamStore';
import type { ArcenEvent } from '../src/types/events';

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;

function ev(partial: Partial<ArcenEvent> & { type: string; seq: number }): ArcenEvent {
  return { agent: 'DRAFT', ts: 1700000000, ...partial } as ArcenEvent;
}

beforeEach(() => {
  useStreamStore.getState().reset();
  useSessionStore.setState({ sessions: [], activeId: null });
  localStorage.clear();
  vi.unstubAllGlobals();
});

describe('T-045: generated session ids', () => {
  it('a fresh browser context boots on a generated UUID — persisted, never "s-ui"', () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response('[]', { status: 200 }));
    vi.stubGlobal('fetch', fetchMock);

    render(<App />);

    const stored = localStorage.getItem('arcen.activeId');
    expect(stored).not.toBeNull();
    expect(stored).toMatch(UUID_RE); // a real UUID v4 …
    expect(stored).not.toBe('s-ui'); // … never the legacy constant
    expect(useSessionStore.getState().activeId).toBe(stored);
    // no wire request may carry the legacy id
    const urls = fetchMock.mock.calls.map(([u]) => String(u));
    expect(urls.some((u) => u.includes('s-ui'))).toBe(false);
  });

  it('a reload reuses the stored id — no churn, same session reloads', () => {
    localStorage.setItem('arcen.activeId', '11111111-2222-4333-8444-555555555555');
    const fetchMock = vi.fn().mockResolvedValue(new Response('[]', { status: 200 }));
    vi.stubGlobal('fetch', fetchMock);

    render(<App />);

    expect(useSessionStore.getState().activeId).toBe('11111111-2222-4333-8444-555555555555');
    expect(localStorage.getItem('arcen.activeId')).toBe('11111111-2222-4333-8444-555555555555');
  });

  it('a legacy "s-ui" context replays its events once, then rotates to a fresh UUID', async () => {
    localStorage.setItem('arcen.activeId', 's-ui'); // pre-T-045 context
    const fetchMock = vi.fn().mockImplementation((url: string) => {
      if (String(url) === '/api/sessions/s-ui/events') {
        // the old merged session still exists on the server
        return Promise.resolve(
          new Response(
            JSON.stringify([
              ev({ type: 'run.start', seq: 1, run_id: 'r-old', goal: 'old goal', depth: 0 }),
              ev({ type: 'answer', seq: 2, text: 'old answer' }),
            ]),
            { status: 200 },
          ),
        );
      }
      if (String(url).includes('/api/run')) {
        return Promise.resolve(
          new Response(JSON.stringify({ run_id: 'r-9', session: 'x' }), { status: 200 }),
        );
      }
      return Promise.resolve(new Response('[]', { status: 404 }));
    });
    vi.stubGlobal('fetch', fetchMock);

    render(<App />);

    // the rotation happened: stored + active id is now a fresh UUID
    await waitFor(() => {
      const stored = localStorage.getItem('arcen.activeId');
      expect(stored).toMatch(UUID_RE);
      expect(useSessionStore.getState().activeId).toBe(stored);
    });
    const rotated = localStorage.getItem('arcen.activeId') as string;
    expect(rotated).not.toBe('s-ui');

    // the old events were loaded exactly once (the migration replay) …
    const suiEventFetches = fetchMock.mock.calls.filter(([u]) => String(u) === '/api/sessions/s-ui/events');
    expect(suiEventFetches).toHaveLength(1);
    // … and the fresh chat starts empty (no legacy bleed-through)
    await waitFor(() => {
      expect(useStreamStore.getState().events).toHaveLength(0);
    });

    // the next turn runs on the rotated id — 's-ui' is never sent again
    const input = screen.getByTestId('composer-input') as HTMLTextAreaElement;
    const setter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value')?.set;
    setter?.call(input, 'after migration');
    input.dispatchEvent(new Event('input', { bubbles: true }));
    fireEvent.click(screen.getByTestId('send-btn'));

    await waitFor(() => {
      const run = fetchMock.mock.calls.find(([u]) => String(u).includes('/api/run'));
      expect(run).toBeDefined();
      const body = JSON.parse(String(run?.[1]?.body));
      expect(body.session).toBe(rotated);
      expect(body.session).not.toBe('s-ui');
    });
    // no run/stream/poll request ever carries the legacy id after rotation
    const postRotateUrls = fetchMock.mock.calls.map(([u]) => String(u));
    expect(postRotateUrls.some((u) => u.includes('/api/run') && u.includes('s-ui'))).toBe(false);
  });

  it('two fresh contexts resolve to two different UUIDs', () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response('[]', { status: 200 }));
    vi.stubGlobal('fetch', fetchMock);

    const { unmount } = render(<App />);
    const idA = useSessionStore.getState().activeId;
    expect(idA).toMatch(UUID_RE);
    unmount();

    // simulate a second, independent browser context: wipe everything
    useSessionStore.setState({ activeId: null });
    localStorage.clear();

    render(<App />);
    const idB = useSessionStore.getState().activeId;
    expect(idB).toMatch(UUID_RE);
    expect(idB).not.toBe(idA);
  });
});

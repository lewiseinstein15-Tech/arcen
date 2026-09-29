// T-046 — per-user session list: cross-context isolation.
// Once ids are generated per browser context (T-045), each context owns its
// own session: a message sent in one context is POSTed to that context's id
// and no context ever reads, streams, or runs the other's session. This test
// simulates two fresh browser contexts (full storage + store wipe between
// them) and pins the isolation so a regression to a shared default id fails.

import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import App from '../src/App';
import { useSessionStore } from '../src/state/sessionStore';
import { useStreamStore } from '../src/state/streamStore';

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;

interface Wire {
  urls: string[];
  runBodies: Array<{ session: string; goal: string }>;
}

/** Render one "browser context", send one message, record every wire call. */
async function useContextOnce(goal: string): Promise<{ id: string; wire: Wire; cleanup: () => void }> {
  const wire: Wire = { urls: [], runBodies: [] };
  const fetchMock = vi.fn().mockImplementation((url: string, init?: RequestInit) => {
    const u = String(url);
    wire.urls.push(u);
    if (u.includes('/api/run')) {
      const body = JSON.parse(String(init?.body)) as { session: string; goal: string };
      wire.runBodies.push(body);
      return Promise.resolve(
        new Response(JSON.stringify({ run_id: 'r-1', session: body.session }), { status: 200 }),
      );
    }
    return Promise.resolve(new Response('[]', { status: 200 }));
  });
  vi.stubGlobal('fetch', fetchMock);

  const { unmount } = render(<App />);
  const id = useSessionStore.getState().activeId as string;

  const input = screen.getByTestId('composer-input') as HTMLTextAreaElement;
  const setter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value')?.set;
  setter?.call(input, goal);
  input.dispatchEvent(new Event('input', { bubbles: true }));
  fireEvent.click(screen.getByTestId('send-btn'));

  await waitFor(() => {
    expect(wire.runBodies.length).toBeGreaterThan(0);
  });

  return {
    id,
    wire,
    cleanup: () => {
      unmount();
      // simulate throwing the whole browser context away
      useStreamStore.getState().reset();
      useSessionStore.setState({ sessions: [], activeId: null });
      localStorage.clear();
      vi.unstubAllGlobals();
    },
  };
}

beforeEach(() => {
  useStreamStore.getState().reset();
  useSessionStore.setState({ sessions: [], activeId: null });
  localStorage.clear();
  vi.unstubAllGlobals();
});

describe('T-046: cross-context session isolation', () => {
  it('two fresh contexts own distinct ids and never touch each other\u2019s session', async () => {
    // ── context A: a fresh browser window ──────────────────────────────
    const a = await useContextOnce('hello from A');
    expect(a.id).toMatch(UUID_RE);
    localStorage.setItem('arcen.activeId', a.id); // A persists its own id
    a.cleanup();

    // ── context B: ANOTHER fresh browser window (storage wiped) ────────
    const b = await useContextOnce('hello from B');
    expect(b.id).toMatch(UUID_RE);

    // the ids differ — no shared default, no collision across contexts
    expect(b.id).not.toBe(a.id);

    // A ran on A's id, B ran on B's id
    expect(a.wire.runBodies[0].session).toBe(a.id);
    expect(a.wire.runBodies[0].goal).toBe('hello from A');
    expect(b.wire.runBodies[0].session).toBe(b.id);
    expect(b.wire.runBodies[0].goal).toBe('hello from B');

    // B never reads, streams, polls, or runs A's session …
    const bTouchesA = b.wire.urls.some((u) => u.includes(a.id));
    expect(bTouchesA).toBe(false);
    // … and A (which pre-dated B) could not have touched B's either
    const aTouchesB = a.wire.urls.some((u) => u.includes(b.id));
    expect(aTouchesB).toBe(false);

    b.cleanup();
  });

  it('a context reload keeps using its own id — still isolated from the other context', async () => {
    const a = await useContextOnce('first context turn');
    const idA = a.id;
    localStorage.setItem('arcen.activeId', idA); // simulate A persisting across reloads
    a.cleanup();

    const b = await useContextOnce('second context turn');
    const idB = b.id;
    expect(idB).not.toBe(idA);
    b.cleanup();

    // "reload" context A: restore its stored id, replay, and send again
    localStorage.setItem('arcen.activeId', idA);
    const wire: Wire = { urls: [], runBodies: [] };
    const fetchMock = vi.fn().mockImplementation((url: string, init?: RequestInit) => {
      const u = String(url);
      wire.urls.push(u);
      if (u.includes('/api/run')) {
        const body = JSON.parse(String(init?.body)) as { session: string; goal: string };
        wire.runBodies.push(body);
        return Promise.resolve(
          new Response(JSON.stringify({ run_id: 'r-2', session: body.session }), { status: 200 }),
        );
      }
      return Promise.resolve(new Response('[]', { status: 200 }));
    });
    vi.stubGlobal('fetch', fetchMock);

    render(<App />);
    expect(useSessionStore.getState().activeId).toBe(idA); // same UUID as before

    const input = screen.getByTestId('composer-input') as HTMLTextAreaElement;
    const setter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value')?.set;
    setter?.call(input, 'context A after reload');
    input.dispatchEvent(new Event('input', { bubbles: true }));
    fireEvent.click(screen.getByTestId('send-btn'));

    await waitFor(() => {
      expect(wire.runBodies.length).toBeGreaterThan(0);
    });
    expect(wire.runBodies[0].session).toBe(idA); // A still runs on A's id
    expect(wire.urls.some((u) => u.includes(idB))).toBe(false); // B stays invisible
    vi.unstubAllGlobals();
  });
});

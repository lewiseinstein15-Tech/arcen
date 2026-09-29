// T-035 — "+ New chat" button (sidebar + top bar).
// Proves: both buttons render; clicking with messages present swaps the
// session id and clears the stream; clicking on an empty chat keeps the
// same session; the previous session remains in the sessions drawer.

import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import App from '../src/App';
import { useDrawerStore } from '../src/state/drawerStore';
import { useSessionStore } from '../src/state/sessionStore';
import { useStreamStore } from '../src/state/streamStore';
import type { ArcenEvent } from '../src/types/events';

function ev(partial: Partial<ArcenEvent> & { type: string; seq: number }): ArcenEvent {
  return { agent: 'DRAFT', ts: 1700000000, ...partial } as ArcenEvent;
}

beforeEach(() => {
  useStreamStore.getState().reset();
  useSessionStore.setState({ sessions: [], activeId: null });
  useDrawerStore.getState().setOpen(false);
  localStorage.clear();
});

describe('T-035: new chat buttons', () => {
  it('sidebar shows the "+ New chat" button and the top bar the compact +', () => {
    render(<App />);
    expect(screen.getByTestId('new-chat-btn')).toBeInTheDocument();
    expect(screen.getByTestId('new-chat-btn')).toHaveTextContent('New chat');
    expect(screen.getByTestId('topbar-plus')).toBeInTheDocument();
  });

  it('click with a non-empty stream → new session id, stream cleared, drawer keeps the old chat', async () => {
    const fetchMock = vi.fn().mockImplementation((url: string) => {
      if (String(url).includes('/api/run')) {
        return Promise.resolve(new Response(JSON.stringify({ run_id: 'r-1', session: 'test-session-a' }), { status: 200 }));
      }
      if (String(url).includes('/api/sessions')) {
        return Promise.resolve(new Response('[]', { status: 200 }));
      }
      return Promise.resolve(new Response('[]', { status: 200 }));
    });
    vi.stubGlobal('fetch', fetchMock);

    render(<App />);
    // put a turn into the stream (as if the user chatted)
    const s = useStreamStore.getState();
    s.apply(ev({ type: 'run.start', seq: 1, run_id: 'r-1', goal: 'hello', depth: 0 }));
    s.apply(ev({ type: 'answer', seq: 2, text: 'hi there' }));
    expect(useStreamStore.getState().events).toHaveLength(2);

    fireEvent.click(screen.getByTestId('new-chat-btn'));

    const activeId = useSessionStore.getState().activeId;
    expect(activeId).not.toBeNull();
    expect(activeId).not.toBe('test-session-a'); // not a shared/hardcoded id
    expect(activeId).toMatch(/^[0-9a-f-]{36}$/); // T-045: generated UUID
    expect(useStreamStore.getState().events).toHaveLength(0); // stream cleared
    // the composer regains focus (new chat is ready to type into)
    await waitFor(() => {
      expect(screen.getByTestId('composer-input')).toHaveFocus();
    });
  });

  it('click with an empty stream keeps the same session (no churn)', () => {
    render(<App />);
    const before = useSessionStore.getState().activeId;
    fireEvent.click(screen.getByTestId('topbar-plus'));
    expect(useSessionStore.getState().activeId).toBe(before);
    expect(useStreamStore.getState().events).toHaveLength(0);
  });

  it('sending after a new chat POSTs to the fresh session id', async () => {
    const runBodies: string[] = [];
    const fetchMock = vi.fn().mockImplementation((url: string, init?: RequestInit) => {
      if (String(url).includes('/api/run')) {
        runBodies.push(String(init?.body));
        return Promise.resolve(new Response(JSON.stringify({ run_id: 'r-9', session: 'x' }), { status: 200 }));
      }
      if (String(url).includes('/api/sessions') && String(url).endsWith('/events')) {
        return Promise.resolve(new Response('[]', { status: 404 }));
      }
      return Promise.resolve(new Response('[]', { status: 200 }));
    });
    vi.stubGlobal('fetch', fetchMock);

    render(<App />);
    // first turn on the default session
    useStreamStore.getState().apply(ev({ type: 'run.start', seq: 1, run_id: 'r-1', goal: 'one', depth: 0 }));
    fireEvent.click(screen.getByTestId('new-chat-btn'));
    const freshId = useSessionStore.getState().activeId;
    expect(freshId).not.toBeNull();

    // type + send into the fresh chat
    const input = screen.getByTestId('composer-input') as HTMLTextAreaElement;
    const setter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value')?.set;
    setter?.call(input, 'fresh hello');
    input.dispatchEvent(new Event('input', { bubbles: true }));
    fireEvent.click(screen.getByTestId('send-btn'));

    await waitFor(() => {
      expect(runBodies.length).toBeGreaterThan(0);
      const body = JSON.parse(runBodies[runBodies.length - 1]);
      expect(body.session).toBe(freshId); // the run targets the fresh chat
      expect(body.goal).toBe('fresh hello');
    });
  });
});

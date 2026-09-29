// T-032 — live optimistic streaming visibility.
// Proves: Send shows the user pill + DRAFT skeleton instantly (before the
// POST resolves); the server's run.start clears the optimistic block;
// events render strictly in seq order even when applied out of order;
// the generating indicator names the working agent and disappears on
// turn completion.

import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, beforeEach, vi } from 'vitest';
import App from '../src/App';
import { useDrawerStore } from '../src/state/drawerStore';
import { useStreamStore } from '../src/state/streamStore';
import type { ArcenEvent } from '../src/types/events';

function ev(partial: Partial<ArcenEvent> & { type: string; seq: number }): ArcenEvent {
  return { agent: 'DRAFT', ts: 1700000000, ...partial } as ArcenEvent;
}

function resetStores() {
  useStreamStore.getState().reset();
  useDrawerStore.getState().setOpen(false);
}

beforeEach(resetStores);

describe('T-032: optimistic pending turn', () => {
  it('Send → optimistic pill + DRAFT skeleton appear immediately, before the POST resolves', async () => {
    let resolveRun: (r: Response) => void = () => {};
    const fetchMock = vi.fn().mockImplementation((url: string) => {
      if (String(url).includes('/api/run')) {
        return new Promise<Response>((resolve) => {
          resolveRun = resolve;
        }); // never resolves during the assertion window
      }
      return Promise.resolve(new Response('[]', { status: 200 }));
    });
    vi.stubGlobal('fetch', fetchMock);

    render(<App />);
    const input = screen.getByTestId('composer-input') as HTMLTextAreaElement;
    const setter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value')?.set;
    setter?.call(input, '2+2');
    input.dispatchEvent(new Event('input', { bubbles: true }));
    fireEvent.click(screen.getByTestId('send-btn'));

    // the optimistic blocks are visible BEFORE the POST resolves
    expect(screen.getByTestId('pending-turn')).toBeInTheDocument();
    expect(screen.getByTestId('draft-skeleton')).toBeInTheDocument();
    expect(screen.getByTestId('pending-turn')).toHaveTextContent('2+2');
    expect(screen.getByTestId('draft-skeleton')).toHaveTextContent('DRAFT');
    // the generating indicator names DRAFT while nothing has streamed yet
    expect(screen.getByTestId('generating')).toHaveTextContent('DRAFT is thinking…');

    resolveRun(new Response(JSON.stringify({ run_id: 'r-1', session: 'test-session-a' }), { status: 200 }));
    await waitFor(() => {
      expect(fetchMock.mock.calls.some(([u]) => String(u).includes('/api/run'))).toBe(true);
    });
  });

  it("the server's run.start clears the optimistic block (no double pill)", () => {
    const s = useStreamStore.getState();
    act(() => s.setPendingTurn('2+2'));
    expect(useStreamStore.getState().pendingTurn).not.toBeNull();
    act(() => {
      s.apply(ev({ type: 'run.start', seq: 1, run_id: 'r-1', goal: '2+2', depth: 0 }));
    });
    expect(useStreamStore.getState().pendingTurn).toBeNull();
  });

  it('submit failure clears the optimistic block', async () => {
    const fetchMock = vi.fn().mockImplementation((url: string) => {
      if (String(url).includes('/api/run')) {
        return Promise.resolve(new Response('nope', { status: 500 }));
      }
      return Promise.resolve(new Response('[]', { status: 200 }));
    });
    vi.stubGlobal('fetch', fetchMock);

    render(<App />);
    const input = screen.getByTestId('composer-input') as HTMLTextAreaElement;
    const setter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value')?.set;
    setter?.call(input, 'broken');
    input.dispatchEvent(new Event('input', { bubbles: true }));
    fireEvent.click(screen.getByTestId('send-btn'));

    await waitFor(() => {
      expect(useStreamStore.getState().pendingTurn).toBeNull();
    });
  });
});

describe('T-032: in-order render (never out of order)', () => {
  it('events applied out of order stay seq-ordered in the store', () => {
    const s = useStreamStore.getState();
    s.apply(ev({ type: 'run.start', seq: 1, run_id: 'r-1', goal: 'g', depth: 0 }));
    s.apply(ev({ type: 'plan', seq: 3, steps: [] }));
    s.apply(ev({ type: 'think', seq: 2, text: 'narration' }));
    const seqs = useStreamStore.getState().events.map((e) => e.seq);
    expect(seqs).toEqual([1, 2, 3]);
  });

  it('a gap self-heals: the late event slots into its position', () => {
    const s = useStreamStore.getState();
    s.apply(ev({ type: 'run.start', seq: 1, run_id: 'r-1', goal: 'g', depth: 0 }));
    s.apply(ev({ type: 'plan', seq: 4, steps: [] }));
    expect(useStreamStore.getState().events.map((e) => e.seq)).toEqual([1, 4]);
    s.apply(ev({ type: 'think', seq: 3, text: 'n' }));
    s.apply(ev({ type: 'plan', seq: 2, steps: [] }));
    expect(useStreamStore.getState().events.map((e) => e.seq)).toEqual([1, 2, 3, 4]);
  });
});

describe('T-032: generating indicator', () => {
  it('names the working agent per the last event; disappears on run.done', () => {
    const s = useStreamStore.getState();
    const { rerender } = render(<App />);

    act(() => s.setPendingTurn('build me a calculator'));
    expect(screen.getByTestId('generating')).toHaveTextContent('DRAFT is thinking…');

    act(() => {
      s.apply(ev({ type: 'run.start', seq: 1, run_id: 'r-1', goal: 'build me a calculator', depth: 0 }));
      s.apply(ev({ type: 'think', seq: 2, text: 'planning' }));
    });
    expect(screen.getByTestId('generating')).toHaveTextContent('DRAFT is thinking…');

    act(() => {
      s.apply(ev({ type: 'command', seq: 3, step: 1, agent: 'FORGE', tool: 'bash', args: { cmd: 'ls' } }));
    });
    expect(screen.getByTestId('generating')).toHaveTextContent('FORGE is working…');

    act(() => {
      s.apply(ev({ type: 'verify.start', seq: 4, agent: 'TEMPER', target: 'x' }));
    });
    expect(screen.getByTestId('generating')).toHaveTextContent('TEMPER is verifying…');

    act(() => {
      s.apply(ev({ type: 'run.done', seq: 5, status: 'ok', steps: 1, duration_s: 1 }));
    });
    expect(screen.queryByTestId('generating')).not.toBeInTheDocument();
    rerender(<App />);
    expect(screen.queryByTestId('generating')).not.toBeInTheDocument();
  });
});

describe('T-033: chronological turn order (newest at bottom)', () => {
  it('three turns applied across replays + live appends stay 1,2,3 top-to-bottom', () => {
    const s = useStreamStore.getState();
    // turn 1 lands live
    s.apply(ev({ type: 'run.start', seq: 1, run_id: 'r-1', goal: 'first', depth: 0 }));
    s.apply(ev({ type: 'answer', seq: 2, text: 'a1' }));
    s.apply(ev({ type: 'run.done', seq: 3, status: 'ok', steps: 0, duration_s: 1 }));
    // turn 2 arrives via the post-POST replay (hydrate replaces everything)
    s.hydrate([
      ev({ type: 'run.start', seq: 1, run_id: 'r-1', goal: 'first', depth: 0 }),
      ev({ type: 'answer', seq: 2, text: 'a1' }),
      ev({ type: 'run.done', seq: 3, status: 'ok', steps: 0, duration_s: 1 }),
      ev({ type: 'run.start', seq: 4, run_id: 'r-2', goal: 'second', depth: 0 }),
      ev({ type: 'answer', seq: 5, text: 'a2' }),
      ev({ type: 'run.done', seq: 6, status: 'ok', steps: 0, duration_s: 1 }),
    ]);
    expect(useStreamStore.getState().events.map((e) => e.seq)).toEqual([1, 2, 3, 4, 5, 6]);
    // turn 3 lands live on top of the replay
    s.apply(ev({ type: 'run.start', seq: 7, run_id: 'r-3', goal: 'third', depth: 0 }));
    s.apply(ev({ type: 'answer', seq: 8, text: 'a3' }));
    const goals = useStreamStore
      .getState()
      .events.filter((e) => e.type === 'run.start')
      .map((e) => (e as unknown as { goal: string }).goal);
    expect(goals).toEqual(['first', 'second', 'third']); // chronological
    expect(useStreamStore.getState().events[useStreamStore.getState().events.length - 1].seq).toBe(8);
  });

  it('hydrate sorts an out-of-order replay ascending (defensive)', () => {
    const s = useStreamStore.getState();
    s.hydrate([
      ev({ type: 'answer', seq: 2, text: 'a1' }),
      ev({ type: 'run.start', seq: 1, run_id: 'r-1', goal: 'first', depth: 0 }),
    ]);
    expect(useStreamStore.getState().events.map((e) => e.seq)).toEqual([1, 2]);
  });
});

// T-043 — a refused run (docker pinned, no daemon) shows the server's
// fix-it message inline: it is a refusal, not a reconnect, and the
// optimistic block clears immediately.
describe('T-043: the docker refusal reaches the chat', () => {
  it('POST /api/run 409 + detail → submit-error banner with the server message', async () => {
    const fetchMock = vi.fn().mockImplementation((url: string) => {
      if (String(url).includes('/api/run')) {
        return Promise.resolve(
          new Response(
            JSON.stringify({
              detail:
                'Sandbox backend is set to docker, but no docker daemon is reachable. Either start docker or change the backend in Settings → Sandbox.',
            }),
            { status: 409 },
          ),
        );
      }
      return Promise.resolve(new Response('[]', { status: 200 }));
    });
    vi.stubGlobal('fetch', fetchMock);

    render(<App />);
    const input = screen.getByTestId('composer-input') as HTMLTextAreaElement;
    const setter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value')?.set;
    setter?.call(input, 'build me a calculator');
    input.dispatchEvent(new Event('input', { bubbles: true }));
    fireEvent.click(screen.getByTestId('send-btn'));

    const banner = await screen.findByTestId('submit-error');
    expect(banner).toHaveTextContent(
      'Sandbox backend is set to docker, but no docker daemon is reachable. Either start docker or change the backend in Settings → Sandbox.',
    );
    // the optimistic block cleared — nothing is "generating"
    await waitFor(() => {
      expect(useStreamStore.getState().pendingTurn).toBeNull();
    });
  });
});

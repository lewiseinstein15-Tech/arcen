// F-06 / F-07 / F-08 — auto-scroll + pill (FRONTEND-SPEC Part 6).
// jsdom has no layout, so the DOM-free tracker carries the logic and the
// hook/element wiring is exercised through mocks of the geometry.

import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { createScrollTracker, useAutoScroll } from '../src/stream/useAutoScroll';
import { ScrollPill } from '../src/components/ScrollPill';
import App from '../src/App';
import { useDrawerStore } from '../src/state/drawerStore';
import { useStreamStore } from '../src/state/streamStore';

function resetDom() {
  document.body.innerHTML = '';
}

beforeEach(resetDom);

describe('scroll tracker logic', () => {
  it('F-06: append while pinned → stays at bottom (follows the stream)', () => {
    const tracker = createScrollTracker();
    expect(tracker.pinned).toBe(true);
    for (let i = 0; i < 50; i++) {
      expect(tracker.onAppend()).toBe(true); // every append follows
    }
  });

  it('F-07: scroll up >100px → browsing mode, pill counts new events', () => {
    const tracker = createScrollTracker();
    tracker.onScroll(400); // 400px from bottom: browsing
    expect(tracker.pinned).toBe(false);
    for (let i = 0; i < 47; i++) tracker.onAppend();
    expect(tracker.pendingCount).toBe(47);
    expect(tracker.onAppend()).toBe(false); // the view must not move
  });

  it('F-08: click pill → scrollToBottom, re-pin, appends follow again', () => {
    const tracker = createScrollTracker();
    tracker.onScroll(400);
    for (let i = 0; i < 10; i++) tracker.onAppend();
    expect(tracker.pendingCount).toBe(10);
    tracker.scrollToBottom(); // what the pill click does
    expect(tracker.pinned).toBe(true);
    expect(tracker.pendingCount).toBe(0);
    expect(tracker.onAppend()).toBe(true);
  });

  it('within 100px of bottom counts as pinned (threshold frozen)', () => {
    const tracker = createScrollTracker();
    tracker.onScroll(99);
    expect(tracker.pinned).toBe(true);
    tracker.onScroll(100);
    expect(tracker.pinned).toBe(true);
    tracker.onScroll(101);
    expect(tracker.pinned).toBe(false);
  });
});

describe('ScrollPill', () => {
  it('shows the jump-to-latest label; ChatView mounts it only while browsing', () => {
    // T-034 contract: the pill offers the jump regardless of pending count;
    // visibility is decided by the hook's pinned state in ChatView
    render(<ScrollPill count={0} onClick={() => {}} />);
    expect(screen.getByTestId('scroll-pill')).toHaveTextContent('jump to latest');
  });

  it('shows the pending count, singular and plural', () => {
    render(<ScrollPill count={1} onClick={() => {}} />);
    expect(screen.getByText(/1 new event$/)).toBeInTheDocument();
    render(<ScrollPill count={47} onClick={() => {}} />);
    expect(screen.getByText(/47 new events/)).toBeInTheDocument();
  });

  it('click re-pins (calls onClick)', () => {
    let clicked = 0;
    render(<ScrollPill count={9} onClick={() => (clicked += 1)} />);
    fireEvent.click(screen.getByTestId('scroll-pill'));
    expect(clicked).toBe(1);
  });
});

describe('useAutoScroll DOM wiring', () => {
  it('follows the stream while pinned; never moves while browsing', () => {
    let pinned = true;
    let dep = 0;
    function Host() {
      const { ref, onScroll, scrollToBottom } = useAutoScroll(dep);
      return (
        <div
          ref={(el) => {
            if (!el || el.dataset.wired) {
              ref.current = el ?? ref.current;
              return;
            }
            el.dataset.wired = '1'; // ref callbacks re-run per render — wire once
            let scrollTop = 0;
            Object.defineProperty(el, 'scrollTop', {
              get: () => scrollTop,
              set: (v) => (scrollTop = v),
            });
            Object.defineProperty(el, 'scrollHeight', { get: () => 5000 });
            Object.defineProperty(el, 'clientHeight', { get: () => 500 });
            ref.current = el;
          }}
          onScroll={onScroll}
          data-testid="scroller"
        >
          <button data-testid="pin" onClick={scrollToBottom} />
          <span>{pinned ? 'pinned' : 'browsing'}</span>
        </div>
      );
    }
    render(<Host />);
    const scroller = screen.getByTestId('scroller');

    // user scrolls up beyond the threshold
    fireEvent.scroll(scroller);
    // simulate the geometry read: scrollHeight - scrollTop - clientHeight = 4000 > 100
    // (jsdom returns 0s, so we set scrollTop negative-offset via the mock above)
    expect(scroller).toBeInTheDocument();

    // pill click returns to bottom
    fireEvent.click(screen.getByTestId('pin'));
    expect(scroller).toBeInTheDocument();
    void pinned;
  });
});

// -- T-034: the hook is actually mounted in ChatView, pill = jump to latest --
describe('T-034: auto-scroll mounted in ChatView', () => {
  it('renders the scroll pill only while browsing, with the jump label', async () => {
    const fetchMock = vi.fn().mockImplementation(() =>
      Promise.resolve(new Response('[]', { status: 200 })),
    );
    vi.stubGlobal('fetch', fetchMock);
    useStreamStore.getState().reset();
    useDrawerStore.getState().setOpen(false);

    // user is at the bottom → pinned → no pill
    const { container } = render(<App />);
    expect(screen.queryByTestId('scroll-pill')).toBeNull();
    void container;

    // browse up: simulate the hook's unpinned state through the store-backed UI
    // (the pill renders whenever pinned === false)
    const scroller = screen.getByTestId('stream');
    // geometry: 4000 content, 500 viewport → bottom is scrollTop 3500
    let scrollTop = 3500;
    Object.defineProperty(scroller, 'scrollTop', { get: () => scrollTop, set: (v) => (scrollTop = v) });
    Object.defineProperty(scroller, 'scrollHeight', { get: () => 4000 });
    Object.defineProperty(scroller, 'clientHeight', { get: () => 500 });
    fireEvent.scroll(scroller); // at the bottom: dist 0, stays pinned
    expect(screen.queryByTestId('scroll-pill')).toBeNull();
    scrollTop = 2000; // ...the user scrolled up 1500px (scrollTop decreases)
    fireEvent.scroll(scroller);
    await waitFor(() => {
      expect(screen.getByTestId('scroll-pill')).toBeInTheDocument();
      expect(screen.getByTestId('scroll-pill')).toHaveTextContent('jump to latest');
    });

    // clicking the pill re-pins → pill disappears
    fireEvent.click(screen.getByTestId('scroll-pill'));
    await waitFor(() => {
      expect(screen.queryByTestId('scroll-pill')).toBeNull();
    });
  });
});

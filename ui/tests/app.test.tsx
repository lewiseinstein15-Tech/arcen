// F-01 · F-02 · F-03 — tokens, app boot, composer send (FRONTEND-SPEC).

import { readFileSync } from 'node:fs';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import App from '../src/App';
import { useDrawerStore } from '../src/state/drawerStore';
import { useStreamStore } from '../src/state/streamStore';

// F-01 — tokens.css loads; 21 custom properties resolve to exact spec hexes
describe('F-01: design tokens', () => {
  const css = readFileSync(`${process.cwd()}/src/styles/tokens.css`, 'utf-8');

  it('declares exactly 21 custom properties', () => {
    const props = [...css.matchAll(/--[\w-]+:/g)];
    expect(props).toHaveLength(21);
  });

  it('matches the Part 3.1 palette hex-for-hex', () => {
    const pairs: Record<string, string> = {
      '--bg': '#0A0B0D',
      '--surface': '#111316',
      '--elevated': '#181B20',
      '--sunken': '#060709',
      '--border-subtle': '#1E2126',
      '--border': '#2A2E35',
      '--border-strong': '#3A3F48',
      '--text': '#E6E8EB',
      '--text-2': '#9BA1A9',
      '--text-3': '#6A7079',
      '--accent': '#FF6B5C',
      '--accent-hi': '#FF8878',
      '--accent-lo': '#D9534A',
      '--success': '#4ADE80',
      '--warn': '#FBBF24',
      '--danger': '#F87171',
      '--info': '#60A5FA',
      '--memory': '#A78BFA',
      '--browse': '#2DD4BF',
    };
    for (const [name, hex] of Object.entries(pairs)) {
      const re = new RegExp(`${name.replace(/-/g, '\\-')}:\\s*${hex}`, 'i');
      expect(css.match(re), `${name} must be ${hex}`).not.toBeNull();
    }
  });

  it('declares the frozen font stacks', () => {
    expect(css).toContain("JetBrains Mono");
    expect(css).toContain('Inter');
  });
});

// F-02 — App boots to ChatView; header, empty stream, composer present
describe('F-02: app boot', () => {
  it('renders header, empty stream and composer', () => {
    render(<App />);
    expect(screen.getByTestId('header')).toBeInTheDocument();
    expect(screen.getByTestId('stream')).toBeInTheDocument();
    expect(screen.getByRole('log')).toHaveAttribute('aria-live', 'polite');
    expect(screen.getByTestId('stream-empty')).toBeInTheDocument(); // empty stream state
    expect(screen.getByTestId('composer')).toBeInTheDocument();
    expect(screen.getByTestId('composer-input')).toBeInTheDocument();
    expect(screen.getByLabelText('ARCEN')).toBeInTheDocument();
  });
});

// F-03 — composer send: type + click ↗ → POST /api/run fired once
describe('F-03: composer send', () => {
  it('type + click send → POST /api/run fired once', async () => {
    const fetchMock = vi.fn().mockImplementation((url: string) => {
      if (String(url).includes('/api/run')) {
        return Promise.resolve(
          new Response(JSON.stringify({ run_id: 'r-1', session: 's-ui' }), { status: 200 }),
        );
      }
      if (String(url).includes('/api/sessions') || String(url).includes('/api/stream')) {
        return Promise.resolve(new Response('[]', { status: 200 }));
      }
      return Promise.resolve(new Response('{}', { status: 200 }));
    });
    vi.stubGlobal('fetch', fetchMock);
    useStreamStore.getState().reset();
    useDrawerStore.getState().setOpen(false);

    render(<App />);
    const input = screen.getByTestId('composer-input') as HTMLTextAreaElement;
    const setter = Object.getOwnPropertyDescriptor(
      window.HTMLTextAreaElement.prototype,
      'value',
    )?.set;
    setter?.call(input, 'fix the failing test in tests/');
    input.dispatchEvent(new Event('input', { bubbles: true }));
    fireEvent.click(screen.getByTestId('send-btn'));

    await waitFor(() => {
      const runCalls = fetchMock.mock.calls.filter(([u]) => String(u).includes('/api/run'));
      expect(runCalls).toHaveLength(1);
      const init = runCalls[0][1] as RequestInit;
      expect(init.method).toBe('POST');
      expect(JSON.parse(String(init.body)).goal).toBe('fix the failing test in tests/');
    });
  });
});

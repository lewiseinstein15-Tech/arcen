// F-01 · F-02 · F-03 — tokens, app boot, composer send (FRONTEND-SPEC).

import { readFileSync } from 'node:fs';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import App from '../src/App';
import { useDrawerStore } from '../src/state/drawerStore';
import { useStreamStore } from '../src/state/streamStore';

// F-01 — tokens.css loads; 36 custom properties resolve to the exact
// v0.2 reference palette (coral #FF6B4A, warm text, white-alpha hairlines)
describe('F-01: design tokens', () => {
  const css = readFileSync(`${process.cwd()}/src/styles/tokens.css`, 'utf-8');

  it('declares exactly 36 custom properties', () => {
    const props = [...css.matchAll(/--[\w-]+:/g)];
    expect(props).toHaveLength(36);
  });

  it('matches the v0.2 reference palette value-for-value', () => {
    const pairs: Record<string, string> = {
      '--bg': '#0A0B0D',
      '--sidebar': '#0D0E10',
      '--surface': '#101114',
      '--elevated': '#14161A',
      '--sunken': '#060709',
      '--hairline': 'rgba(255, 255, 255, 0.06)',
      '--hairline-2': 'rgba(255, 255, 255, 0.10)',
      '--hover-wash': 'rgba(255, 255, 255, 0.03)',
      '--chip-bg': 'rgba(255, 255, 255, 0.05)',
      '--chip-border': 'rgba(255, 255, 255, 0.08)',
      '--border-subtle': 'rgba(255, 255, 255, 0.06)',
      '--border': 'rgba(255, 255, 255, 0.10)',
      '--border-strong': 'rgba(255, 255, 255, 0.16)',
      '--text': '#E8E6E3',
      '--text-2': '#8A8A8A',
      '--text-3': '#5A5A5A',
      '--placeholder': '#6A6A6A',
      '--accent': '#FF6B4A',
      '--accent-hi': '#FF7A55',
      '--accent-lo': '#E05538',
      '--accent-08': 'rgba(255, 107, 74, 0.08)',
      '--accent-10': 'rgba(255, 107, 74, 0.10)',
      '--accent-20': 'rgba(255, 107, 74, 0.20)',
      '--accent-35': 'rgba(255, 107, 74, 0.35)',
      '--accent-40': 'rgba(255, 107, 74, 0.40)',
      '--on-accent': '#FFFFFF',
      '--success': '#4ADE80',
      '--warn': '#FBBF24',
      '--danger': '#F87171',
      '--info': '#60A5FA',
      '--memory': '#A78BFA',
      '--browse': '#2DD4BF',
      '--deco-warm': '#3A2018',
      '--deco-warm-0': 'rgba(58, 32, 24, 0)',
      '--backdrop': 'rgba(0, 0, 0, 0.6)',
    };
    for (const [name, value] of Object.entries(pairs)) {
      const re = new RegExp(
        `${name.replace(/-/g, '\\-')}:\\s*${value.replace(/[()\\[\].,]/g, (m) => `\\${m}`)}`,
        'i',
      );
      expect(css.match(re), `${name} must be ${value}`).not.toBeNull();
    }
  });

  it('is monospace-first: JetBrains Mono everywhere, Inter removed (v0.2)', () => {
    expect(css).toContain('JetBrains Mono');
    expect(css).not.toContain('Inter');
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

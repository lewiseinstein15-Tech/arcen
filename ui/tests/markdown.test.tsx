// F-09 — answer renders GFM table, $…$ KaTeX, Shiki code block, mermaid SVG;
// copy button copies the raw source (FRONTEND-SPEC Part 5).

import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { CopyButton } from '../src/markdown/Code';
import { Markdown } from '../src/markdown/Markdown';

const ANSWER = [
  '# Report',
  '',
  '| step | result |',
  '| ---- | ------ |',
  '| 1    | pass   |',
  '',
  'The value $E = mc^2$ holds.',
  '',
  '```python',
  'print("hello")',
  '```',
].join('\n');

describe('F-09: markdown pipeline', () => {
  it('renders a GFM table', () => {
    render(<Markdown>{ANSWER}</Markdown>);
    expect(screen.getByRole('table')).toBeInTheDocument();
    expect(screen.getByText('pass')).toBeInTheDocument();
  });

  it('renders inline math through KaTeX', async () => {
    render(<Markdown>{ANSWER}</Markdown>);
    // KaTeX emits .katex spans (html output)
    await waitFor(() => {
      const katex = document.querySelectorAll('.katex');
      expect(katex.length).toBeGreaterThan(0);
    });
  });

  it('renders a code block with a copy button', () => {
    render(<Markdown>{ANSWER}</Markdown>);
    expect(screen.getAllByTestId('copy-btn').length).toBeGreaterThan(0);
    expect(screen.getByText(/print\("hello"\)/)).toBeInTheDocument();
  });

  it('copy button writes the RAW source and flips to copied for 1.5s', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.assign(navigator, { clipboard: { writeText } });
    render(<CopyButton text={'print("hello")\n'} />);
    fireEvent.click(screen.getByTestId('copy-btn'));
    await waitFor(() => expect(writeText).toHaveBeenCalledWith('print("hello")\n'));
    expect(screen.getByText('copied')).toBeInTheDocument();
    // reverts after 1.5s
    await waitFor(
      () => expect(screen.getByText('copy')).toBeInTheDocument(),
      { timeout: 2500 },
    );
  }, 5000);

  it('mermaid fences render through the lazy diagram path (no hard crash)', async () => {
    const fence = '```mermaid\ngraph TD; A-->B;\n```';
    render(<Markdown>{fence}</Markdown>);
    // jsdom cannot lay out SVG; assert the lazy chunk mounted its container
    await waitFor(
      () => {
        const el = document.querySelector('.mermaid') ?? document.querySelector('.mermaid-fallback');
        expect(el).not.toBeNull();
      },
      { timeout: 5000 },
    );
  });
});

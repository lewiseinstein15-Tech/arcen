import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { UsageBlock } from '../src/events/UsageBlock';
import type { UsageEvent } from '../src/types/events';

const old: UsageEvent = { type: 'usage', seq: 1, ts: 0, tokens: {input: 3, output: 2}, cost_usd: 0 };
describe('A-08 usage', () => {
  it('renders unknown for old and explicitly unmeasured payloads', () => {
    const { rerender } = render(<UsageBlock event={old} />);
    expect(screen.getByText(/tokens unknown/)).toHaveTextContent('cost unknown');
    rerender(<UsageBlock event={{...old, measured: false, usage_source: 'unknown', cost_source: 'unknown'}} />);
    expect(screen.getByText(/tokens unknown/)).toHaveTextContent('cost unknown');
  });
  it('shows measured tokens but not unknown cost', () => {
    render(<UsageBlock event={{...old, measured: true, usage_source: 'provider', cost_source: 'unknown'}} />);
    expect(screen.getByText(/3 in/)).toHaveTextContent('cost unknown');
  });
});

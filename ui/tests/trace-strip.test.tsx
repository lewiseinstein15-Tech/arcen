// Run trace: a waterfall over folded blocks. Locks the wire units — event.ts
// is epoch SECONDS, so a 4.9s run must read "4.9s" and a 90ms step "90ms",
// not "0.0s" and "0ms".

import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { TraceStrip } from '../src/components/TraceStrip';
import type { FoldedBlock } from '../src/stream/fold';
import type { ArcenEvent } from '../src/types/events';

function block(
  primary: ArcenEvent,
  done?: Extract<ArcenEvent, { type: 'command.done' }>,
): FoldedBlock {
  return { seq: primary.seq, primary, done };
}

const T0 = 1727500000.0;

const THINK: ArcenEvent = { type: 'think', seq: 1, ts: T0, agent: 'DRAFT', text: 'planning' };
const COMMAND: ArcenEvent = {
  type: 'command',
  seq: 2,
  ts: T0 + 1.0,
  agent: 'FORGE',
  step: 1,
  tool: 'bash',
  args: { cmd: 'pytest' },
};
const COMMAND_DONE: ArcenEvent = {
  type: 'command.done',
  seq: 3,
  ts: T0 + 1.09,
  step: 1,
  ok: true,
  result: { stdout: 'ok' },
  duration_s: 0.09,
};
const VERIFY: ArcenEvent = {
  type: 'verify.start',
  seq: 4,
  ts: T0 + 2.0,
  agent: 'TEMPER',
  target: 'pytest',
};

describe('TraceStrip', () => {
  it('reports wall-clock seconds and per-step milliseconds', () => {
    render(
      <TraceStrip
        blocks={[block(THINK), block(COMMAND, COMMAND_DONE), block(VERIFY)]}
      />,
    );
    const meta = screen.getByTestId('trace-strip').textContent ?? '';
    expect(meta).toContain('3 steps');
    expect(meta).toContain('2.0s');
    expect(meta).toContain('90ms');
    expect(meta).not.toContain('0.0s');
  });

  it('colours each segment by the agent that owned it', () => {
    render(
      <TraceStrip blocks={[block(THINK), block(COMMAND, COMMAND_DONE), block(VERIFY)]} />,
    );
    expect(screen.getByTestId('trace-seg-1').className).toContain('trace-draft');
    expect(screen.getByTestId('trace-seg-2').className).toContain('trace-forge');
    expect(screen.getByTestId('trace-seg-4').className).toContain('trace-temper');
  });

  it('stays out of the way for a single block', () => {
    render(<TraceStrip blocks={[block(THINK)]} />);
    expect(screen.queryByTestId('trace-strip')).not.toBeInTheDocument();
  });
});

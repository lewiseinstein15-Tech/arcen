// ARCEN — run trace (v0.2). A slim waterfall over the folded blocks: every
// segment is one block on the wall clock, coloured by the agent that owned
// it, so "where did the time go" is answerable without reading timestamps.
//
// Derived entirely from events the stream already carries (each has ts, and
// the done/update variants mark the end) — the trace adds no server surface
// and cannot disagree with the blocks below it.

import type { FoldedBlock } from '../stream/fold';
import type { ArcenEvent } from '../types/events';

const AGENT_OF: Record<string, 'draft' | 'forge' | 'temper'> = {
  'run.start': 'draft',
  think: 'draft',
  plan: 'draft',
  'plan.update': 'draft',
  answer: 'draft',
  memory: 'draft',
  spawn: 'forge',
  'spawn.done': 'forge',
  command: 'forge',
  'command.done': 'forge',
  'file.diff': 'forge',
  'verify.start': 'temper',
  'step.pass': 'temper',
  'step.fail': 'temper',
  usage: 'temper',
  'run.done': 'temper',
  'run.error': 'temper',
};

function endOf(block: FoldedBlock): number {
  const marks: number[] = [block.primary.ts];
  if (block.done) marks.push(block.done.ts);
  if (block.update) marks.push(block.update.ts);
  for (const v of block.verdicts ?? []) marks.push(v.ts);
  return Math.max(...marks);
}

function labelOf(event: ArcenEvent): string {
  switch (event.type) {
    case 'think':
      return 'DRAFT think';
    case 'plan':
      return 'DRAFT plan';
    case 'spawn':
      return 'FORGE spawn';
    case 'command':
      return `FORGE ${event.tool}`;
    case 'file.diff':
      return `FORGE patch ${event.path}`;
    case 'verify.start':
      return 'TEMPER verify';
    case 'step.pass':
    case 'step.fail':
      return `TEMPER ${event.type === 'step.pass' ? 'pass' : 'fail'} #${event.step}`;
    case 'answer':
      return 'DRAFT answer';
    case 'usage':
      return 'usage';
    default:
      return event.type;
  }
}

export function TraceStrip({ blocks }: { blocks: FoldedBlock[] }) {
  if (blocks.length < 2) return null;

  // event.ts is epoch SECONDS (the wire contract), not milliseconds
  const start = Math.min(...blocks.map((b) => b.primary.ts));
  const end = Math.max(...blocks.map(endOf));
  const span = Math.max(end - start, 0.001);

  const segments = blocks.map((b) => {
    const from = ((b.primary.ts - start) / span) * 100;
    const width = Math.max(((endOf(b) - b.primary.ts) / span) * 100, 0.6);
    const agent = AGENT_OF[b.primary.type] ?? 'draft';
    return {
      key: b.seq,
      agent,
      from: Math.min(from, 100),
      width: Math.min(width, 100 - from),
      ms: (endOf(b) - b.primary.ts) * 1000,
      title: `${labelOf(b.primary)} · ${((endOf(b) - b.primary.ts) * 1000).toFixed(0)}ms`,
    };
  });

  const slowest = segments.reduce((a, b) => (b.ms > a.ms ? b : a), segments[0]);

  return (
    <div className="trace-strip" data-testid="trace-strip">
      <span className="trace-meta">
        {blocks.length} steps · {span.toFixed(1)}s · slowest: {slowest.title}
      </span>
      <div className="trace-bar" role="img" aria-label="run timeline">
        {segments.map((s) => (
          <span
            key={s.key}
            className={`trace-seg trace-${s.agent}`}
            style={{ left: `${s.from}%`, width: `${s.width}%` }}
            title={s.title}
            data-testid={`trace-seg-${s.key}`}
          />
        ))}
      </div>
    </div>
  );
}

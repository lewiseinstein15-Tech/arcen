// F-04 — mock NDJSON stream of all 17 event types → all 17 components render
// with correct glyph/color (FRONTEND-SPEC Part 2 / Part 3.3). In-place events
// (plan.update, command.done, spawn.done, step.pass/step.fail) fold into
// their parent blocks per Part 1.

import { render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { BlockFor } from '../src/events';
import { foldEvents } from '../src/stream/fold';
import type { ArcenEvent } from '../src/types/events';

const NDJSON_LINES = [
  '{"seq":1,"type":"run.start","run_id":"r-01J9","goal":"fix the failing test","depth":0,"ts":1727500000.0}',
  '{"seq":2,"type":"think","agent":"DRAFT","text":"Read the test first, then the module.","ts":1727500000.1}',
  '{"seq":3,"type":"plan","agent":"DRAFT","steps":[{"id":1,"title":"read failing test","tool":"file.read"}],"ts":1727500000.2}',
  '{"seq":4,"type":"plan.update","agent":"DRAFT","reason":"test bug","steps":[{"id":1,"title":"edit assertion","tool":"file.edit"}],"ts":1727500001.3}',
  '{"seq":5,"type":"spawn","parent":"DRAFT","name":"TEST-READER","task":"extract assertion","depth":1,"ts":1727500000.4}',
  '{"seq":6,"type":"spawn.done","name":"TEST-READER","ok":true,"calls":3,"duration_s":12.4,"ts":1727500012.9}',
  '{"seq":7,"type":"command","agent":"FORGE","step":2,"tool":"bash","args":{"cmd":"pytest -q tests/"},"ts":1727500002.0}',
  '{"seq":8,"type":"command.done","step":2,"ok":true,"result":{"stdout":"12 passed","exit":0},"duration_s":3.2,"ts":1727500005.2}',
  '{"seq":9,"type":"file.diff","path":"tests/test_pay.py","patch":"--- a/t\\n+++ b/t\\n@@ -1 +1 @@","ts":1727500001.5}',
  '{"seq":10,"type":"verify.start","agent":"TEMPER","target":"tests/","ts":1727500005.5}',
  '{"seq":11,"type":"step.pass","step":3,"checks":["pytest -q tests/  # 12 passed"],"ts":1727500006.0}',
  '{"seq":12,"type":"step.fail","step":3,"reason":"assert 4 == 5","retry":1,"ts":1727500006.1}',
  '{"seq":13,"type":"answer","text":"The test expected 5; calc returns 4. Fixed.","ts":1727500006.4}',
  '{"seq":14,"type":"memory","op":"write","entity":"calc()","fact":"returns int sum","ts":1727500006.4}',
  '{"seq":15,"type":"usage","tokens":{"input":18432,"output":1204},"cost_usd":0.021,"ts":1727500006.4}',
  '{"seq":16,"type":"run.done","status":"ok","steps":3,"duration_s":6.5,"ts":1727500006.4}',
  '{"seq":17,"type":"run.error","code":"SANDBOX_UNAVAILABLE","message":"docker daemon not reachable","ts":1727500006.4}',
];

const EVENTS: ArcenEvent[] = NDJSON_LINES.map((l) => JSON.parse(l) as ArcenEvent);

// glyph + token color per event type — straight from Part 3.3
const EXPECTED: Record<string, { glyph: string; color: string }> = {
  'run.start': { glyph: '◆', color: 'var(--accent)' },
  think: { glyph: '✱', color: 'var(--text-3)' },
  plan: { glyph: '▸', color: 'var(--accent)' },
  'plan.update': { glyph: '↻', color: 'var(--warn)' },
  spawn: { glyph: '⎇', color: 'var(--info)' },
  'spawn.done': { glyph: '✓', color: 'var(--success)' },
  command: { glyph: '❯', color: 'var(--accent)' },
  'command.done': { glyph: '●', color: 'var(--success)' },
  'file.diff': { glyph: 'Δ', color: 'var(--info)' },
  'verify.start': { glyph: '⊙', color: 'var(--memory)' },
  'step.pass': { glyph: '⚑', color: 'var(--success)' },
  'step.fail': { glyph: '✗', color: 'var(--danger)' },
  answer: { glyph: '✦', color: 'var(--accent-hi)' },
  memory: { glyph: '⬡', color: 'var(--memory)' },
  usage: { glyph: '¤', color: 'var(--text-2)' },
  'run.done': { glyph: '◇', color: 'var(--success)' },
  'run.error': { glyph: '✗', color: 'var(--danger)' },
};

// which event types fold into parents (no standalone block)
const FOLDED_TYPES = new Set(['plan.update', 'command.done', 'spawn.done', 'step.pass', 'step.fail']);

describe('F-04: the 17 event types render', () => {
  it('renders every event type with the correct glyph and color', () => {
    const folded = foldEvents(EVENTS);
    render(
      <div>
        {folded.map((block) => (
          <BlockFor key={block.seq} block={block} depth={0} />
        ))}
      </div>,
    );

    for (const event of EVENTS) {
      if (FOLDED_TYPES.has(event.type)) {
        // folded events assert their folded content below
        continue;
      }
      const el = document.querySelector(`[data-seq="${event.seq}"]`);
      expect(el, `missing block for ${event.type}`).not.toBeNull();
      // plan.update folds into the plan block (↻); verify verdicts accumulate
      // and the latest drives the block glyph (⚑ pass / ✗ fail) — Part 1
      const foldedBlock = folded.find((b) => b.seq === event.seq);
      const latestVerdict = foldedBlock?.verdicts?.[foldedBlock.verdicts.length - 1];
      const effectiveType =
        event.type === 'plan' && foldedBlock?.update
          ? 'plan.update'
          : event.type === 'verify.start' && latestVerdict
            ? latestVerdict.type
            : event.type;
      const expected = EXPECTED[effectiveType];
      const glyphEl = within(el as HTMLElement).getAllByText(expected.glyph, { exact: true })[0];
      expect(glyphEl).toHaveStyle({ color: expected.color });
    }

    // folded content is visible through its parent
    expect(screen.queryByText(/3 calls · 12\.4s/)).toBeInTheDocument(); // spawn.done
    expect(screen.queryByText(/● 3\.2s/)).toBeInTheDocument(); // command.done
    expect(screen.queryByText(/pytest -q tests\/\s+# 12 passed/)).toBeInTheDocument(); // step.pass
    expect(screen.queryByText(/step 3 failed/)).toBeInTheDocument(); // step.fail
    expect(screen.queryByText(/re-plan · test bug/)).toBeInTheDocument(); // plan.update ↻
  });

  it('run.error renders a fatal banner with its code', () => {
    const folded = foldEvents([EVENTS[16]]);
    render(
      <div>
        {folded.map((block) => (
          <BlockFor key={block.seq} block={block} depth={0} />
        ))}
      </div>,
    );
    const banner = document.querySelector('[data-seq="17"]');
    expect(banner).not.toBeNull();
    expect(banner?.getAttribute('aria-label')).toContain('SANDBOX_UNAVAILABLE');
  });
});

// ARCEN — RunStartBlock: ◆ the goal line (always visible).

import { memo } from 'react';
import type { RunStartEvent } from '../types/events';
import { GLYPHS } from './render';

export const RunStartBlock = memo(function RunStartBlock({ event }: { event: RunStartEvent }) {
  const { glyph, color } = GLYPHS['run.start'];
  return (
    <article className="block run-start" data-seq={event.seq} aria-label={`ARCEN starting: ${event.goal}`}>
      <span className="glyph" style={{ color }}>
        {glyph}
      </span>
      <span className="who">{event.run_id}</span>
      <span className="goal">{event.goal}</span>
    </article>
  );
});

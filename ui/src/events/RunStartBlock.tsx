// ARCEN — RunStartBlock: ◆ the user's goal, rendered as a message pill.
// The user's own words get the bubble (reference look); agent events stay
// flat panels. The ◆ glyph keeps its Part 3.3 accent color inside the pill.

import { memo } from 'react';
import type { RunStartEvent } from '../types/events';
import { GLYPHS } from './render';

export const RunStartBlock = memo(function RunStartBlock({ event }: { event: RunStartEvent }) {
  const { glyph, color } = GLYPHS['run.start'];
  return (
    <article className="block run-start" data-seq={event.seq} aria-label={`ARCEN starting: ${event.goal}`}>
      <div className="user-pill">
        <span className="glyph" style={{ color }} aria-hidden="true">
          {glyph}
        </span>
        <span className="user-tag">YOU</span>
        <span className="goal">{event.goal}</span>
      </div>
    </article>
  );
});

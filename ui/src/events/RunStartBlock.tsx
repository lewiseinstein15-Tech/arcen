// ARCEN — RunStartBlock: ◆ the user's goal, rendered as the user message
// pill (v0.2 reference look): right-aligned coral-hairline pill, transparent
// background, timestamp + double-check beneath. The ◆ glyph keeps its
// Part 3.3 accent color inside the pill.

import { memo } from 'react';
import type { RunStartEvent } from '../types/events';
import { GLYPHS, fmtTime } from './render';
import { DoubleCheckIcon } from '../components/Icons';

export const RunStartBlock = memo(function RunStartBlock({ event }: { event: RunStartEvent }) {
  const { glyph, color } = GLYPHS['run.start'];
  const ts = fmtTime(event.ts);
  return (
    <article
      className="block run-start"
      data-seq={event.seq}
      aria-label={`ARCEN starting: ${event.goal}`}
    >
      <div className="user-pill">
        <span className="glyph" style={{ color }} aria-hidden="true">
          {glyph}
        </span>
        <span className="goal">{event.goal}</span>
      </div>
      {ts && (
        <div className="msg-ts with-check">
          <span>{ts}</span>
          <DoubleCheckIcon size={14} className="ts-check" />
        </div>
      )}
    </article>
  );
});

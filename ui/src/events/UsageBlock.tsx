// ARCEN — UsageBlock: ¤ token/cost meter, inline in the footer area.

import { memo } from 'react';
import type { UsageEvent } from '../types/events';
import { GLYPHS } from './render';

export const UsageBlock = memo(function UsageBlock({ event }: { event: UsageEvent }) {
  const { glyph, color } = GLYPHS['usage'];
  return (
    <article
      className="block usage"
      data-seq={event.seq}
      aria-label={`usage: ${event.tokens.input + event.tokens.output} tokens, $${event.cost_usd}`}
    >
      <span className="glyph" style={{ color }}>
        {glyph}
      </span>
      <span className="meta">
        {event.tokens.input} in · {event.tokens.output} out · ${event.cost_usd.toFixed(3)}
      </span>
    </article>
  );
});

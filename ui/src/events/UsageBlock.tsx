// ARCEN — UsageBlock: ¤ token/cost meter, inline in the footer area.

import { memo } from 'react';
import type { UsageEvent } from '../types/events';
import { GLYPHS } from './render';

export const UsageBlock = memo(function UsageBlock({ event }: { event: UsageEvent }) {
  const { glyph, color } = GLYPHS['usage'];
  const known = event.measured === true;
  const costKnown = known && (event.cost_source === 'provider' || event.cost_source === 'estimated');
  const tokens = known ? `${event.tokens.input} in · ${event.tokens.output} out` : 'tokens unknown';
  const cost = costKnown ? `$${event.cost_usd.toFixed(3)}` : 'cost unknown';
  return (
    <article
      className="block usage"
      data-seq={event.seq}
      aria-label={`usage: ${tokens}, ${cost}`}
    >
      <span className="glyph" style={{ color }}>
        {glyph}
      </span>
      <span className="meta">
        {tokens} · {cost}
      </span>
    </article>
  );
});

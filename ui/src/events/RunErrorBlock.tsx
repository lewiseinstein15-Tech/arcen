// ARCEN — RunErrorBlock: ✗ fatal error banner. Expanded, never collapses.

import { memo } from 'react';
import type { RunErrorEvent } from '../types/events';
import { GLYPHS } from './render';

export const RunErrorBlock = memo(function RunErrorBlock({ event }: { event: RunErrorEvent }) {
  const { glyph, color } = GLYPHS['run.error'];
  return (
    <article
      className="block run-error"
      data-seq={event.seq}
      style={{ border: '1px solid var(--danger)' }}
      aria-label={`error ${event.code}: ${event.message}`}
    >
      <span className="glyph" style={{ color }}>
        {glyph}
      </span>
      <span className="who">{event.code}</span>
      <p className="body">{event.message}</p>
    </article>
  );
});

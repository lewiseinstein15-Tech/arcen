// ARCEN — MemoryBlock: ⬡ recall/write notice (violet, collapsed by default).

import { memo, useState } from 'react';
import type { MemoryEvent } from '../types/events';
import { GLYPHS } from './render';
import { Chevron } from './Chevron';

export const MemoryBlock = memo(function MemoryBlock({ event }: { event: MemoryEvent }) {
  const { glyph, color } = GLYPHS['memory'];
  const [open, setOpen] = useState(false);
  return (
    <article className="block memory" data-seq={event.seq} aria-label={`memory ${event.op}: ${event.entity}`}>
      <button className="block-head" onClick={() => setOpen(!open)} aria-expanded={open}>
        <span className="glyph" style={{ color }}>
          {glyph}
        </span>
        <span className="meta">
          {event.op} · {event.entity}
        </span>
        <Chevron open={open} />
      </button>
      {open && <p className="body">{event.fact}</p>}
    </article>
  );
});

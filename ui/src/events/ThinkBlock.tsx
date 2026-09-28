// ARCEN — ThinkBlock: ✱ DRAFT narration, collapsed by default, streams open.

import { memo, useState } from 'react';
import type { ThinkEvent } from '../types/events';
import { GLYPHS, truncate } from './render';
import { Chevron } from './Chevron';

export const ThinkBlock = memo(function ThinkBlock({ event }: { event: ThinkEvent }) {
  const { glyph, color } = GLYPHS['think'];
  const [open, setOpen] = useState(false);
  return (
    <article className="block think" data-seq={event.seq} aria-label={`${event.agent}: ${truncate(event.text, 60)}`}>
      <button className="block-head" onClick={() => setOpen(!open)} aria-expanded={open}>
        <span className="glyph" style={{ color }}>
          {glyph}
        </span>
        <span className="who">{event.agent}</span>
        {!open && <span className="preview">{truncate(event.text, 72)}</span>}
        <Chevron open={open} />
      </button>
      {open && <p className="body">{event.text}</p>}
    </article>
  );
});

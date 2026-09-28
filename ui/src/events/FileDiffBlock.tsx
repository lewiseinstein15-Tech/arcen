// ARCEN — FileDiffBlock: Δ unified diff, collapsed by default, copyable.

import { memo, useState } from 'react';
import type { FileDiffEvent } from '../types/events';
import { GLYPHS, truncate } from './render';
import { Chevron } from './Chevron';

export const FileDiffBlock = memo(function FileDiffBlock({ event }: { event: FileDiffEvent }) {
  const { glyph, color } = GLYPHS['file.diff'];
  const [open, setOpen] = useState(false); // collapsed; click to open
  return (
    <article className="block file-diff" data-seq={event.seq} aria-label={`diff of ${event.path}`}>
      <button className="block-head" onClick={() => setOpen(!open)} aria-expanded={open}>
        <span className="glyph" style={{ color }}>
          {glyph}
        </span>
        <span className="path">{truncate(event.path, 72)}</span>
        <Chevron open={open} />
      </button>
      {open && <pre className="diff">{event.patch}</pre>}
    </article>
  );
});

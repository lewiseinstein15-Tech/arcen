// ARCEN — SpawnBlock: ⎇ sub-agent line; spawn.done (✓) folds into the footer.

import { memo, useState } from 'react';
import type { SpawnDoneEvent, SpawnEvent } from '../types/events';
import { GLYPHS, indent, truncate } from './render';

export const SpawnBlock = memo(function SpawnBlock({
  event,
  done,
  depth,
}: {
  event: SpawnEvent;
  done?: SpawnDoneEvent;
  depth: number;
}) {
  const { glyph, color } = GLYPHS['spawn'];
  const [open, setOpen] = useState(true);
  return (
    <article
      className="block spawn"
      style={{ paddingLeft: `${indent(depth)}ch` }}
      data-seq={event.seq}
      aria-label={`spawned ${event.name}: ${truncate(event.task ?? '', 60)}`}
    >
      <button className="block-head" onClick={() => setOpen(!open)} aria-expanded={open}>
        <span className="glyph" style={{ color }}>
          {glyph}
        </span>
        <span className="who">{event.name}</span>
        <span className="task">{truncate(event.task ?? '', 64)}</span>
        {done && (
          <span className="meta">
            ✓ {done.calls} calls · {done.duration_s}s
          </span>
        )}
      </button>
      {open && <div className="spawn-children" data-depth={depth + 1} />}
    </article>
  );
});

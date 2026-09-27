// ARCEN — CommandBlock: ❯ tool call; command.done (● / ✗) folds in place.

import { memo, useState } from 'react';
import type { CommandDoneEvent, CommandEvent } from '../types/events';
import { GLYPHS, summarizeArgs } from './render';

export const CommandBlock = memo(function CommandBlock({
  event,
  done,
}: {
  event: CommandEvent;
  done?: CommandDoneEvent;
}) {
  const finished = Boolean(done);
  const [open, setOpen] = useState(true); // expanded while running
  const { glyph, color } = GLYPHS['command'];
  return (
    <article
      className={`block command ${finished ? 'is-done' : 'is-running'}`}
      data-seq={event.seq}
      aria-label={`${event.tool} ${summarizeArgs(event.args)}`}
    >
      <button className="block-head" onClick={() => setOpen(!open)} aria-expanded={open}>
        <span className="glyph" style={{ color }}>
          {glyph}
        </span>
        <span className="tool">{event.tool}</span>
        <code className="args">{summarizeArgs(event.args)}</code>
        {finished && done && (
          <span
            className="meta"
            style={{ color: done.ok ? 'var(--success)' : 'var(--danger)' }}
          >
            {done.ok ? '●' : '✗'} {done.duration_s}s
          </span>
        )}
      </button>
      {finished && open && done?.result && (
        <details className="result" open>
          <summary className="meta">result</summary>
          <pre>{JSON.stringify(done.result, null, 2)}</pre>
        </details>
      )}
    </article>
  );
});

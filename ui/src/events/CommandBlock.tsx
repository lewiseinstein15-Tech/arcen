// ARCEN — CommandBlock: ❯ tool call; command.done (● / ✗) folds in place.
// The result renders as TERMINAL OUTPUT (stdout, stderr, exit code) —
// never a raw JSON dump.

import { memo, useState } from 'react';
import type { CommandDoneEvent, CommandEvent } from '../types/events';
import { GLYPHS, summarizeArgs } from './render';
import { Chevron } from './Chevron';

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
  const stdout = typeof done?.result?.stdout === 'string' ? done.result.stdout : '';
  const stderr = typeof done?.result?.stderr === 'string' ? done.result.stderr : '';
  const exit = typeof done?.result?.exit === 'number' ? done.result.exit : undefined;
  const hasOutput = Boolean(stdout.trim() || stderr.trim());
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
        <Chevron open={open} />
      </button>
      {finished && open && done && (
        <div className="result">
          {hasOutput ? (
            <>
              {stdout.trim() && <pre>{stdout.replace(/\n$/, '')}</pre>}
              {stderr.trim() && <pre className="is-stderr">{stderr.replace(/\n$/, '')}</pre>}
            </>
          ) : (
            <pre className="result-exit">(no output)</pre>
          )}
          {exit !== undefined && (
            <span className="result-exit">
              exit {exit}
              {stderr.trim() && exit !== 0 ? ' — see stderr above' : ''}
            </span>
          )}
        </div>
      )}
    </article>
  );
});

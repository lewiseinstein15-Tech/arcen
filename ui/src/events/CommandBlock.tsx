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
  // A failed step nests its captured output under `detail`; file tools return
  // a structured object with no streams at all.
  const result = done?.result ?? {};
  const detail = (result.detail ?? {}) as Record<string, unknown>;
  const stream = (key: 'stdout' | 'stderr') => {
    if (typeof detail[key] === 'string') return detail[key] as string;
    return typeof result[key] === 'string' ? (result[key] as string) : '';
  };
  const stdout = stream('stdout');
  const stderr = stream('stderr') || (typeof result.error === 'string' ? result.error : '');
  const exit =
    typeof detail.exit === 'number'
      ? detail.exit
      : typeof result.exit === 'number'
        ? result.exit
        : undefined;
  const fileContent =
    event.tool === 'file.read' && typeof result.content === 'string' ? result.content : '';
  const structured =
    !stdout.trim() &&
    !stderr.trim() &&
    !fileContent.trim() &&
    exit === undefined &&
    Object.keys(result).length > 0;
  const hasOutput = Boolean(stdout.trim() || stderr.trim() || fileContent.trim() || structured);
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
              {fileContent.trim() && <pre>{fileContent.replace(/\n$/, '')}</pre>}
              {structured && <pre>{JSON.stringify(result, null, 2)}</pre>}
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

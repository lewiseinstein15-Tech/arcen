// ARCEN — VerifyBlock: ⊙ TEMPER verify; step.pass (⚑) / step.fail (✗) lines
// fold in and accumulate. Latest verdict drives the block state.

import { memo, useState } from 'react';
import type { StepFailEvent, StepPassEvent, VerifyStartEvent } from '../types/events';
import { GLYPHS } from './render';

type Verdict = StepPassEvent | StepFailEvent;

export const VerifyBlock = memo(function VerifyBlock({
  event,
  verdicts = [],
}: {
  event: VerifyStartEvent | StepPassEvent | StepFailEvent;
  verdicts?: Verdict[];
}) {
  const latest = verdicts.length ? verdicts[verdicts.length - 1] : undefined;
  const failed = latest?.type === 'step.fail';
  const passed = latest?.type === 'step.pass';
  const [open, setOpen] = useState(true);
  const { glyph, color } = GLYPHS['verify.start'];

  if (event.type !== 'verify.start' && verdicts.length === 0) {
    // a bare pass/fail without a verify.start parent renders its own line
    if (event.type === 'step.pass') {
      return (
        <article
          className="block verify is-pass"
          data-seq={event.seq}
          aria-label={`step ${event.step} passed`}
        >
          <span className="glyph" style={{ color: 'var(--success)' }}>
            ⚑
          </span>
          <span className="who">step {event.step}</span>
          {event.checks.map((c) => (
            <span className="meta" key={c}>
              {c}
            </span>
          ))}
        </article>
      );
    }
    return (
      <article
        className="block verify is-fail"
        data-seq={event.seq}
        aria-label={`Step ${event.step} failed: ${event.reason}`}
      >
        <button className="block-head" onClick={() => setOpen(!open)} aria-expanded={open}>
          <span className="glyph" style={{ color: 'var(--danger)' }}>
            ✗
          </span>
          <span className="who">step {event.step} failed</span>
          <span className="meta">{event.retry > 0 ? `retry ${event.retry}` : 'retry pending'}</span>
        </button>
        {open && <p className="body">{event.reason}</p>}
      </article>
    );
  }

  const target = event.type === 'verify.start' ? event.target : '';
  return (
    <article
      className={`block verify ${failed ? 'is-fail' : passed ? 'is-pass' : ''}`}
      data-seq={event.seq}
      aria-label={`verifying ${target}`}
    >
      <button className="block-head" onClick={() => setOpen(!open)} aria-expanded={open}>
        <span
          className="glyph"
          style={{ color: failed ? 'var(--danger)' : passed ? 'var(--success)' : color }}
        >
          {failed ? '✗' : passed ? '⚑' : glyph}
        </span>
        <span className="who">{event.type === 'verify.start' ? event.agent : 'TEMPER'}</span>
        <span className="meta">{target}</span>
      </button>
      {open &&
        verdicts.map((v) =>
          v.type === 'step.pass' ? (
            <div className="verify-line is-pass" key={v.seq}>
              <span className="glyph" style={{ color: 'var(--success)' }}>
                ⚑
              </span>
              <span className="meta">
                step {v.step} · {v.checks.join(', ')}
              </span>
            </div>
          ) : (
            <div className="verify-line is-fail" key={v.seq}>
              <span className="glyph" style={{ color: 'var(--danger)' }}>
                ✗
              </span>
              <span className="meta">
                step {v.step} failed · {v.reason} {v.retry > 0 ? `(retry ${v.retry})` : ''}
              </span>
            </div>
          ),
        )}
    </article>
  );
});

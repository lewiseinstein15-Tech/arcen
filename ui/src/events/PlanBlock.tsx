// ARCEN — PlanBlock: ▸ steps checklist; plan.update (↻) mutates it in place.

import { memo, useState } from 'react';
import type { PlanEvent, PlanUpdateEvent } from '../types/events';
import { GLYPHS } from './render';

export const PlanBlock = memo(function PlanBlock({
  event,
  update,
}: {
  event: PlanEvent | PlanUpdateEvent;
  update?: PlanUpdateEvent;
}) {
  const [open, setOpen] = useState(true); // plans open by default
  const isUpdate = update !== undefined;
  const style = isUpdate ? GLYPHS['plan.update'] : GLYPHS['plan'];
  const agent = update ? update.agent : event.agent;
  const steps = update ? update.steps : event.steps;
  const reason = update ? update.reason : '';
  return (
    <article
      className={`block plan ${isUpdate ? 'is-update' : ''}`}
      data-seq={event.seq}
      aria-label={`plan: ${steps.length} steps${isUpdate ? `, re-planned: ${reason}` : ''}`}
    >
      <button className="block-head" onClick={() => setOpen(!open)} aria-expanded={open}>
        <span className="glyph" style={{ color: style.color }}>
          {style.glyph}
        </span>
        <span className="who">{agent}</span>
        <span className="meta">
          {isUpdate ? `re-plan · ${reason}` : `plan · ${steps.length} steps`}
        </span>
      </button>
      {open && (
        <ol className="plan-steps">
          {steps.map((s) => (
            <li key={s.id} className="plan-step">
              <span className="meta">{s.id}.</span> {s.title}
              {s.tool && <code className="meta"> [{s.tool}]</code>}
            </li>
          ))}
        </ol>
      )}
    </article>
  );
});

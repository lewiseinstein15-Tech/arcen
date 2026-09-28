// ARCEN — AnswerBlock (v0.2 reference look): the bot message —
// 40px avatar with a 2px coral ring and the triangle mark, name row
// (✦ + "Agentic Engineer" + green online dot), monospace prose body,
// timestamp below. Markdown pipeline: gfm · math · shiki · mermaid (Part 5).

import { memo } from 'react';
import type { AnswerEvent } from '../types/events';
import { GLYPHS, fmtTime } from './render';
import { LogoMark } from '../components/LogoMark';
import { Markdown } from '../markdown/Markdown';

export const AnswerBlock = memo(function AnswerBlock({ event }: { event: AnswerEvent }) {
  const { glyph, color } = GLYPHS['answer'];
  const ts = fmtTime(event.ts);
  return (
    <article
      className="bot-message"
      data-seq={event.seq}
      aria-label={`answer: ${event.text.slice(0, 60)}`}
    >
      <div className="bot-avatar" aria-hidden="true">
        <LogoMark height={20} />
      </div>
      <div className="bot-content">
        <div className="bot-name-row">
          <span className="glyph" style={{ color }} aria-hidden="true">
            {glyph}
          </span>
          <span className="bot-name">Agentic Engineer</span>
          <span className="bot-dot" aria-hidden="true" />
        </div>
        <div className="answer-prose prose">
          <Markdown>{event.text}</Markdown>
        </div>
        {ts && <div className="msg-ts">{ts}</div>}
      </div>
    </article>
  );
});

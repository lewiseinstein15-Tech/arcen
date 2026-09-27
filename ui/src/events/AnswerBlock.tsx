// ARCEN — AnswerBlock: ✦ the only Inter prose on the page.
// Markdown pipeline: gfm · math · shiki · mermaid (Part 5).

import { memo } from 'react';
import type { AnswerEvent } from '../types/events';
import { GLYPHS } from './render';
import { Markdown } from '../markdown/Markdown';

export const AnswerBlock = memo(function AnswerBlock({ event }: { event: AnswerEvent }) {
  const { glyph, color } = GLYPHS['answer'];
  return (
    <article className="block answer" data-seq={event.seq} aria-label={`answer: ${event.text.slice(0, 60)}`}>
      <span className="glyph" style={{ color }}>
        {glyph}
      </span>
      <div className="answer-prose prose">
        <Markdown>{event.text}</Markdown>
      </div>
    </article>
  );
});

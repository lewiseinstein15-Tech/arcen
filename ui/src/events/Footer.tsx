// ARCEN — Footer: usage rollup + status, pinned at the end (Part 3.5).

import { memo } from 'react';
import type { RunDoneEvent } from '../types/events';
import { GLYPHS } from './render';

export const Footer = memo(function Footer({ event }: { event: RunDoneEvent }) {
  const { glyph, color } = GLYPHS['run.done'];
  const status = event.verification_status === 'unverified' ? 'unverified' : event.status;
  return (
    <footer
      className="stream-footer"
      data-seq={event.seq}
      aria-label={`turn complete, ${event.steps} steps, ${status}`}
    >
      <span className="glyph" style={{ color }}>
        {glyph}
      </span>
      <span className="meta">
        {event.steps} steps · {event.duration_s}s
      </span>
      <span className={`status ${event.status}`}>{status}</span>
    </footer>
  );
});

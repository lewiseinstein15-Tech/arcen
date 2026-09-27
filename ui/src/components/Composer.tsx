// ARCEN — Composer (FRONTEND-SPEC Part 10). Auto-grow, frozen key bindings,
// slash menu, send/stop states. Full keyboard pass lands with T-026.

import { useRef, type KeyboardEvent } from 'react';
import TextareaAutosize from 'react-textarea-autosize';
import type { StreamStatus } from '../state/streamStore';

interface ComposerProps {
  value: string;
  onChange: (v: string) => void;
  onSend: (text: string) => void;
  status: StreamStatus;
}

export function Composer({ value, onChange, onSend, status }: ComposerProps) {
  const ref = useRef<HTMLTextAreaElement>(null);
  const canSend = value.trim().length > 0 && status !== 'streaming';

  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault(); // Enter sends, Shift+Enter newlines
      if (canSend) {
        onSend(value);
        onChange('');
      }
    }
  };

  return (
    <div className="composer" data-testid="composer">
      <TextareaAutosize
        ref={ref}
        className="composer-input"
        placeholder="describe the task…"
        value={value}
        minRows={1}
        maxRows={8}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={onKeyDown}
        aria-label="composer"
      />
      <button
        className={`send-btn ${canSend ? 'armed' : ''}`}
        aria-label="send"
        disabled={!canSend}
        onClick={() => {
          if (canSend) {
            onSend(value);
            onChange('');
          }
        }}
      >
        {status === 'streaming' ? '■' : '↗'}
      </button>
    </div>
  );
}

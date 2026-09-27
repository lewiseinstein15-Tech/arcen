// ARCEN — ChatView: Stream (role="log") + Composer. The UI renders events;
// it does not hide them (FRONTEND-SPEC Part 0).

import { useState } from 'react';
import { useStreamStore } from '../state/streamStore';
import { submitRun } from '../stream/reader';
import { Composer } from './Composer';

export function ChatView() {
  const events = useStreamStore((s) => s.events);
  const status = useStreamStore((s) => s.status);
  const [draft, setDraft] = useState('');

  const send = (text: string) => {
    if (!text.trim()) return;
    void submitRun(text);
  };

  return (
    <main className="chat-view" data-testid="chat-view">
      <div className="stream" role="log" aria-live="polite" data-testid="stream" tabIndex={0}>
        {events.length === 0 && (
          <div className="stream-empty" data-testid="stream-empty">
            <p className="empty-line">◆ ready</p>
            <p className="empty-sub">
              send a goal — DRAFT plans, FORGE executes, TEMPER verifies. every step lands here.
            </p>
          </div>
        )}
      </div>
      <Composer value={draft} onChange={setDraft} onSend={send} status={status} />
    </main>
  );
}

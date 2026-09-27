// ARCEN — ChatView: Stream (role="log") + Composer. The UI renders events;
// it does not hide them (FRONTEND-SPEC Part 0). Events fold in place per
// Part 1 before rendering.

import { useEffect, useMemo, useState } from 'react';
import { useStreamStore } from '../state/streamStore';
import { foldEvents } from '../stream/fold';
import { consumeStream, submitRun } from '../stream/reader';
import { BlockFor } from '../events';
import { Composer } from './Composer';

export function ChatView({ sessionId = 's-ui' }: { sessionId?: string }) {
  const events = useStreamStore((s) => s.events);
  const status = useStreamStore((s) => s.status);
  const [draft, setDraft] = useState('');
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    consumeStream(
      sessionId,
      useStreamStore.getState().apply,
      controller.signal,
    ).catch((err) => {
      if (!controller.signal.aborted) setError(String(err));
    });
    return () => controller.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId]);

  const folded = useMemo(() => foldEvents(events), [events]);

  const send = (text: string) => {
    if (!text.trim()) return;
    void submitRun(text, sessionId);
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
        {folded.map((block) => (
          <BlockFor key={block.seq} block={block} depth={0} />
        ))}
      </div>
      {error && (
        <div className="stream-error" role="alert">
          reconnecting… {error}
        </div>
      )}
      <Composer value={draft} onChange={setDraft} onSend={send} status={status} />
    </main>
  );
}

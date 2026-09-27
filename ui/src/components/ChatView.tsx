// ARCEN — ChatView: Stream (role="log") + Composer. The UI renders events;
// it does not hide them (FRONTEND-SPEC Part 0). Events fold in place per
// Part 1 before rendering. Reload → replay + draft restore (Part 8).

import { useEffect, useMemo, useState } from 'react';
import { useStreamStore } from '../state/streamStore';
import { foldEvents } from '../stream/fold';
import { consumeStream, submitRun } from '../stream/reader';
import { loadDraft, loadLastSeq, saveDraft, saveLastSeq } from '../state/persist';
import { BlockFor } from '../events';
import { Composer } from './Composer';

export function ChatView({ sessionId = 's-ui' }: { sessionId?: string }) {
  const events = useStreamStore((s) => s.events);
  const status = useStreamStore((s) => s.status);
  const lastSeq = useStreamStore((s) => s.lastSeq);
  const [draft, setDraft] = useState(() => loadDraft()); // composer draft survives reload
  const [error, setError] = useState<string | null>(null);

  // replay from the API first, then follow the live stream (Part 8)
  useEffect(() => {
    const controller = new AbortController();
    let alive = true;

    async function boot() {
      const seen = loadLastSeq(sessionId);
      try {
        const res = await fetch(`/api/sessions/${sessionId}/events`);
        if (res.ok) {
          const replayed = (await res.json()) as import('../types/events').ArcenEvent[];
          if (alive && replayed.length > 0) {
            useStreamStore.getState().hydrate(replayed);
          }
        }
      } catch {
        // replay is best-effort; the live stream still works
      }
      consumeStream(
        sessionId,
        (e) => {
          if (!alive) return;
          useStreamStore.getState().apply(e);
          saveLastSeq(sessionId, e.seq);
        },
        controller.signal,
        seen,
      ).catch((err) => {
        if (alive && !controller.signal.aborted) setError(String(err));
      });
    }
    void boot();
    return () => {
      alive = false;
      controller.abort();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId]);

  // persist the draft as it changes (Part 8)
  useEffect(() => {
    saveDraft(draft);
  }, [draft]);

  const folded = useMemo(() => foldEvents(events), [events]);
  void lastSeq; // exposed for tests / reconnect bookkeeping

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

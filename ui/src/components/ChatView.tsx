// ARCEN — ChatView: Stream (role="log") + Composer. The UI renders events;
// it does not hide them (FRONTEND-SPEC Part 0). Events fold in place per
// Part 1 before rendering. Reload → replay + draft restore (Part 8).
//
// Live-stream lifecycle (stream-fix):
// - /api/sessions/<id>/events is the authority for "what we have seen";
//   localStorage lastSeq may belong to a previous server process and is
//   never trusted for resume.
// - exactly ONE stream attach at a time; the server closes each stream
//   after a terminal event, the next send() re-attaches (one GET per turn).
// - reconnect ladder 500ms/1s/2s/5s, 5 consecutive failures → pill with a
//   manual retry; from the 3rd failure a 1s /events poll guarantees the
//   reply is visible even if the stream route dies.

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useStreamStore } from '../state/streamStore';
import { foldEvents } from '../stream/fold';
import { consumeStream, submitRun } from '../stream/reader';
import { useAutoScroll } from '../stream/useAutoScroll';
import { loadDraft, saveDraft, saveLastSeq } from '../state/persist';
import { BlockFor } from '../events';
import { fmtTime } from '../events/render';
import type { ArcenEvent } from '../types/events';
import { Composer } from './Composer';
import { ScrollPill } from './ScrollPill';
import { autoScrollPreference } from './SettingsView';

const BACKOFF_MS = [500, 1000, 2000, 5000]; // delay before retry N (attempt 1 is immediate)
const MAX_FAILURES = 5; // stop retrying after 5 consecutive failures
const POLL_AFTER_FAILURES = 3; // failover: poll /events every 1s from here on
const POLL_MS = 1000;

export function ChatView({ sessionId = 's-ui' }: { sessionId?: string }) {
  const events = useStreamStore((s) => s.events);
  const status = useStreamStore((s) => s.status);
  const pendingTurn = useStreamStore((s) => s.pendingTurn);
  const setPendingTurn = useStreamStore((s) => s.setPendingTurn);
  const clearPendingTurn = useStreamStore((s) => s.clearPendingTurn);
  const [draft, setDraft] = useState(() => loadDraft()); // composer draft survives reload
  const [error, setError] = useState<string | null>(null);
  // T-043: a refused run (docker pinned, no daemon) shows the server's
  // fix-it message inline — it is not a reconnect, it is a refusal.
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [retryTick, setRetryTick] = useState(0);
  const attachCtl = useRef<AbortController | null>(null);
  const attached = useRef(false);
  const pollTimer = useRef<number | null>(null);

  const stopPoll = useCallback(() => {
    if (pollTimer.current !== null) {
      window.clearInterval(pollTimer.current);
      pollTimer.current = null;
    }
  }, []);

  const startPoll = useCallback(() => {
    if (pollTimer.current !== null) return; // already polling
    pollTimer.current = window.setInterval(async () => {
      try {
        const res = await fetch(`/api/sessions/${sessionId}/events`);
        if (!res.ok) return;
        const replayed = (await res.json()) as ArcenEvent[];
        if (!replayed.length) return;
        const store = useStreamStore.getState();
        for (const e of replayed) {
          if (typeof e.seq === 'number' && e.seq > store.lastSeq) store.apply(e);
        }
        const last = replayed[replayed.length - 1];
        if (last.type === 'run.done' || last.type === 'run.error') stopPoll(); // turn complete
      } catch {
        // keep polling — the next tick may catch up
      }
    }, POLL_MS);
  }, [sessionId, stopPoll]);

  // one live stream at a time; exponential backoff; poll failover
  const attach = useCallback(
    async (fromSeq: number) => {
      attachCtl.current?.abort();
      const controller = new AbortController();
      attachCtl.current = controller;
      attached.current = true;
      const onEvent = (e: ArcenEvent) => {
        useStreamStore.getState().apply(e);
        if (typeof e.seq === 'number') saveLastSeq(sessionId, e.seq);
      };
      try {
        let failures = 0;
        for (;;) {
          try {
            await consumeStream(sessionId, onEvent, controller.signal, fromSeq);
            setError(null); // clean close (stream.done) — turn delivered
            return;
          } catch (err) {
            if (controller.signal.aborted) return;
            failures += 1;
            if (failures >= POLL_AFTER_FAILURES) startPoll(); // guarantee liveness
            if (failures >= MAX_FAILURES) {
              setError(String(err)); // pill with the manual retry button
              return;
            }
            setError(`stream failed — retrying (${failures}/${MAX_FAILURES})`);
            await new Promise((r) => setTimeout(r, BACKOFF_MS[Math.min(failures - 1, BACKOFF_MS.length - 1)]));
            fromSeq = useStreamStore.getState().lastSeq; // resume from what we have
          }
        }
      } finally {
        if (attachCtl.current === controller) {
          attachCtl.current = null;
          attached.current = false;
        }
      }
    },
    [sessionId, startPoll],
  );

  // replay from the API first, then follow the live stream (Part 8)
  useEffect(() => {
    let alive = true;

    async function boot() {
      // server truth first: /events is the authority for the last seen seq
      // (a localStorage seq can be "in the future" after a server restart)
      let seen = 0;
      let exists = false;
      try {
        const res = await fetch(`/api/sessions/${sessionId}/events`);
        if (res.ok) {
          exists = true;
          const replayed = (await res.json()) as ArcenEvent[];
          if (alive && replayed.length > 0) {
            useStreamStore.getState().hydrate(replayed);
            seen = replayed[replayed.length - 1].seq;
          } else if (alive) {
            useStreamStore.getState().reset(); // fresh/empty chat (T-035 session switch)
          }
        }
      } catch {
        // replay is best-effort; the live stream still works
      }
      if (!alive) return;
      // a session that exists nowhere has nothing to stream — the first
      // send() attaches after POST /api/run creates it (no 404 spinning)
      if (exists) await attach(seen);
    }
    void boot();
    return () => {
      alive = false;
      attachCtl.current?.abort();
      stopPoll();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId, retryTick]);

  // persist the draft as it changes (Part 8)
  useEffect(() => {
    saveDraft(draft);
  }, [draft]);

  const folded = useMemo(() => foldEvents(events), [events]);

  // T-034: auto-scroll actually mounted — ref on the scroll container,
  // effect keyed on the visible-content growth, pill while browsing.
  // T-036: the General section can turn pinning off (localStorage pref).
  const [scrollEnabled, setScrollEnabled] = useState(autoScrollPreference());
  useEffect(() => {
    const onWinFocus = () => setScrollEnabled(autoScrollPreference());
    window.addEventListener('focus', onWinFocus);
    return () => window.removeEventListener('focus', onWinFocus);
  }, []);
  const scrollDep = `${events.length}-${pendingTurn ? 1 : 0}-${scrollEnabled ? 1 : 0}`;
  const { ref: streamRef, onScroll: handleScroll, pinned, pendingCount, scrollToBottom } = useAutoScroll(scrollDep, scrollEnabled);

  const send = (text: string) => {
    if (!text.trim()) return;
    setSubmitError(null); // a fresh send clears a previous refusal
    // T-032: the message and the DRAFT skeleton show the instant Send is
    // pressed — before the POST resolves, before the first stream event
    setPendingTurn(text);
    void submitRun(text, sessionId)
      .then(async () => {
        // catch up on anything emitted between POST and now (server truth),
        // then attach ONE stream from the last seen seq — never from 0
        // (ticket #7: this kills the double-render / refresh-required bug)
        let topSeq = useStreamStore.getState().lastSeq;
        try {
          const res = await fetch(`/api/sessions/${sessionId}/events`);
          if (res.ok) {
            const replayed = (await res.json()) as ArcenEvent[];
            if (replayed.length > 0) {
              useStreamStore.getState().hydrate(replayed);
              topSeq = replayed[replayed.length - 1].seq;
            }
          }
        } catch {
          // best-effort catch-up; the live stream covers the rest
        }
        if (!attached.current) await attach(topSeq);
      })
      .catch((err) => {
        // submit failures surface here — a T-043 refusal carries the
        // server's detail ("Sandbox backend is set to docker, but no
        // docker daemon is reachable…"), anything else the status code
        clearPendingTurn();
        setSubmitError(err instanceof Error ? err.message : String(err));
      });
  };

  const retry = () => {
    setError(null);
    stopPoll();
    setRetryTick((t) => t + 1); // re-runs boot: /events truth + fresh attach
  };

  // the generating indicator: which agent is working right now
  const lastType = events.length ? events[events.length - 1].type : null;
  const workingPhrase = useMemo(() => {
    if (lastType === null) return 'DRAFT is thinking…';
    if (
      ['command', 'command.done', 'file.diff', 'spawn', 'spawn.done'].includes(lastType)
    ) {
      return 'FORGE is working…';
    }
    if (['verify.start', 'step.pass', 'step.fail'].includes(lastType)) {
      return 'TEMPER is verifying…';
    }
    return 'DRAFT is thinking…';
  }, [lastType]);
  const working = pendingTurn !== null || status === 'streaming';

  return (
    <main className="chat-view" data-testid="chat-view">
      <div
        className="stream"
        role="log"
        aria-live="polite"
        data-testid="stream"
        tabIndex={0}
        ref={streamRef}
        onScroll={handleScroll}
      >
        {events.length === 0 && (
          <div className="stream-empty" data-testid="stream-empty">
            <span className="empty-mark" aria-hidden="true">
              ◆
            </span>
            <p className="empty-line">ready.</p>
            <p className="empty-sub">
              send a goal — DRAFT plans, FORGE executes, TEMPER verifies.
              <br />
              every step lands here, live.
            </p>
          </div>
        )}
        {folded.map((block) => (
          <BlockFor key={block.seq} block={block} depth={0} />
        ))}
        {pendingTurn && (
          <div className="pending-turn" data-testid="pending-turn">
            <article className="block run-start pending-pill">
              <div className="user-pill">
                <span className="glyph" style={{ color: 'var(--accent)' }} aria-hidden="true">
                  ◆
                </span>
                <span className="goal">{pendingTurn.text}</span>
              </div>
              <div className="msg-ts with-check">
                <span>{fmtTime(pendingTurn.at / 1000)}</span>
              </div>
            </article>
            <article className="block draft-skeleton" data-testid="draft-skeleton" aria-live="polite">
              <div className="block-head">
                <span className="glyph" style={{ color: 'var(--accent)' }} aria-hidden="true">
                  ◆
                </span>
                <span className="who">DRAFT</span>
                <span className="skeleton-time">{fmtTime(pendingTurn.at / 1000)}</span>
              </div>
              <span className="skeleton-bar" aria-hidden="true" />
            </article>
          </div>
        )}
        {status === 'streaming' && (
          <span className="stream-cursor" aria-hidden="true" data-testid="stream-cursor">
            |
          </span>
        )}
      </div>
      {working && (
        <div className="generating" data-testid="generating" role="status">
          <span className="gen-dot" aria-hidden="true" />
          <span className="gen-label">{pendingTurn ? 'DRAFT is thinking…' : workingPhrase}</span>
        </div>
      )}
      {!pinned && (
        <ScrollPill count={pendingCount} onClick={scrollToBottom} />
      )}
      {error && (
        <div className="stream-error" role="alert" data-testid="stream-error">
          <span>reconnecting… {error}</span>
          <button type="button" className="retry-btn" data-testid="stream-retry" onClick={retry}>
            retry
          </button>
        </div>
      )}
      {submitError && (
        <div className="stream-error" role="alert" data-testid="submit-error">
          <span>{submitError}</span>
        </div>
      )}
      <Composer value={draft} onChange={setDraft} onSend={send} status={status} />
      <div className="kb-hints" data-testid="kb-hints">
        <div className="hints-group">
          <span className="kbd">⌘</span>
          <span className="kbd">K</span>
          <span className="hint-label">Quick actions</span>
          <span className="hint-sep" aria-hidden="true">
            |
          </span>
          <span className="kbd">/</span>
          <span className="hint-label">Commands</span>
          <span className="hint-sep" aria-hidden="true">
            |
          </span>
          <span className="kbd">⌘</span>
          <span className="kbd">Enter</span>
          <span className="hint-label">Send</span>
        </div>
        <div className="version-line">
          <span className="version-dot" aria-hidden="true" />
          Agentic Engineer v1.0
        </div>
      </div>
    </main>
  );
}

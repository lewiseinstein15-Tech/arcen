// ARCEN — stream consumption (FRONTEND-SPEC Part 7).
// One partial-line buffer: a command.done split across TCP chunks is never
// half-rendered. Malformed JSON logs + toasts; the stream itself does not die.
// The server closes each stream with a {"type":"stream.done"} transport
// frame after a terminal event — seeing it (or clean EOF) ends the read.

import type { ArcenEvent } from '../types/events';

export class StreamError extends Error {
  status: number;
  /** Server-provided explanation (e.g. the T-043 docker refusal detail). */
  detail?: string;
  constructor(status: number, detail?: string) {
    super(detail || `stream failed with ${status}`);
    this.status = status;
    this.detail = detail;
  }
}

function isDoneFrame(parsed: unknown): boolean {
  return (parsed as { type?: string } | null)?.type === 'stream.done';
}

export async function consumeStream(
  sessionId: string,
  onEvent: (e: ArcenEvent) => void,
  signal?: AbortSignal,
  lastEventId?: number,
): Promise<void> {
  const headers: Record<string, string> = {};
  if (lastEventId !== undefined) headers['Last-Event-ID'] = String(lastEventId);

  // 404 = the session has no live emitter yet — the boot state before the
  // first /api/run. That is not an error: wait quietly and attach as soon
  // as the session goes live (the UI must not spam a reconnect banner).
  // The server now also replays disk-backed sessions, so this only spins
  // for sessions that exist nowhere at all.
  let res: Response;
  for (;;) {
    res = await fetch(`/api/stream?session=${sessionId}`, { signal, headers });
    if (res.status !== 404) break;
    if (signal?.aborted) return;
    await new Promise((r) => setTimeout(r, 1500));
    if (signal?.aborted) return;
  }
  if (!res.ok || !res.body) throw new StreamError(res.status);

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split('\n');
    buffer = lines.pop() ?? ''; // keep the partial line
    for (const line of lines) {
      if (!line.trim()) continue;
      let parsed: ArcenEvent;
      try {
        parsed = JSON.parse(line) as ArcenEvent;
      } catch (err) {
        console.error('malformed stream line', err); // the stream does not die
        continue;
      }
      if (isDoneFrame(parsed)) return; // clean close — the turn is over
      onEvent(parsed);
    }
  }
  if (buffer.trim()) {
    try {
      const tail = JSON.parse(buffer) as ArcenEvent;
      if (!isDoneFrame(tail)) onEvent(tail);
    } catch (err) {
      console.error('malformed stream tail', err);
    }
  }
}

export async function submitRun(goal: string, session?: string): Promise<{ run_id: string; session: string }> {
  const res = await fetch('/api/run', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ goal, session }),
  });
  if (!res.ok) {
    // the server's detail travels with the error — the T-043 docker
    // refusal ("Sandbox backend is set to docker, but no docker daemon
    // is reachable…") must reach the user, not collapse into a status code
    let detail: string | undefined;
    try {
      const body = (await res.json()) as { detail?: string } | null;
      if (body && typeof body.detail === 'string') detail = body.detail;
    } catch {
      /* non-JSON error body — fall back to the status code */
    }
    throw new StreamError(res.status, detail);
  }
  return (await res.json()) as { run_id: string; session: string };
}

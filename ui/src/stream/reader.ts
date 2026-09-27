// ARCEN — stream consumption (FRONTEND-SPEC Part 7).
// One partial-line buffer: a command.done split across TCP chunks is never
// half-rendered. Malformed JSON logs + toasts; the stream itself does not die.

import type { ArcenEvent } from '../types/events';

export class StreamError extends Error {
  status: number;
  constructor(status: number) {
    super(`stream failed with ${status}`);
    this.status = status;
  }
}

export async function consumeStream(
  sessionId: string,
  onEvent: (e: ArcenEvent) => void,
  signal?: AbortSignal,
  lastEventId?: number,
): Promise<void> {
  const headers: Record<string, string> = {};
  if (lastEventId !== undefined) headers['Last-Event-ID'] = String(lastEventId);
  const res = await fetch(`/api/stream?session=${sessionId}`, { signal, headers });
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
      try {
        onEvent(JSON.parse(line) as ArcenEvent);
      } catch (err) {
        console.error('malformed stream line', err); // the stream does not die
      }
    }
  }
  if (buffer.trim()) {
    try {
      onEvent(JSON.parse(buffer) as ArcenEvent);
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
  if (!res.ok) throw new StreamError(res.status);
  return (await res.json()) as { run_id: string; session: string };
}

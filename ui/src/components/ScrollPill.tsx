// ARCEN — ScrollPill: floats above the composer when the user is browsing.
// Hidden while pinned; label is "↓ jump to latest" (T-034) with the pending
// event count when one or more landed out of view. Click = scrollToBottom +
// re-pin. 120ms fade, no fade under prefers-reduced-motion (Part 6/13).

export function ScrollPill({ count, onClick }: { count: number; onClick: () => void }) {
  return (
    <button className="scroll-pill" data-testid="scroll-pill" onClick={onClick}>
      <span className="pill-arrow" aria-hidden="true">
        ↓
      </span>
      <span className="pill-count">jump to latest</span>
      {count > 0 && (
        <span className="pill-count meta">
          {count} new {count === 1 ? 'event' : 'events'}
        </span>
      )}
    </button>
  );
}

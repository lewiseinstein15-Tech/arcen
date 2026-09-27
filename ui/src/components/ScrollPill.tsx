// ARCEN — ScrollPill: floats above the composer when the user is browsing.
// Hidden while pinned; click = scrollToBottom + re-pin. 120ms fade, and no
// fade under prefers-reduced-motion (Part 6 / Part 13).

export function ScrollPill({
  count,
  onClick,
}: {
  count: number;
  onClick: () => void;
}) {
  if (count <= 0) return null;
  return (
    <button className="scroll-pill" data-testid="scroll-pill" onClick={onClick}>
      <span className="pill-arrow">▼</span>
      <span className="pill-count">
        {count} new {count === 1 ? 'event' : 'events'}
      </span>
    </button>
  );
}

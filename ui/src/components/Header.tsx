// ARCEN — Header: drawer button · wordmark · status dot · theme toggle (inert).
// Mobile header is fixed 48px; drawer button is a 44×44 touch target (Part 11).

import { useDrawerStore } from '../state/drawerStore';
import { useStreamStore } from '../state/streamStore';

export function Header() {
  const status = useStreamStore((s) => s.status);
  const setOpen = useDrawerStore((s) => s.setOpen);
  return (
    <header className="app-header" data-testid="header">
      <button
        className="drawer-btn"
        aria-label="open sessions"
        data-testid="drawer-btn"
        onClick={() => setOpen(true)}
      >
        ☰
      </button>
      <div className="wordmark" aria-label="ARCEN">
        <span className="wordmark-mark" aria-hidden="true">
          ◆
        </span>
        A&nbsp;R&nbsp;C&nbsp;E&nbsp;N
      </div>
      <div className="header-right">
        <span className={`status-dot ${status}`} role="img" aria-label={`stream ${status}`} />
        <button className="theme-toggle" aria-label="toggle theme" disabled title="dark only in v0.1">
          ◐
        </button>
      </div>
    </header>
  );
}

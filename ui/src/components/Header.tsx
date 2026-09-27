// ARCEN — Header: wordmark · status dot · theme toggle (inert, dark-only).

import { useStreamStore } from '../state/streamStore';

export function Header() {
  const status = useStreamStore((s) => s.status);
  return (
    <header className="app-header" data-testid="header">
      <button className="drawer-btn" aria-label="open sessions" disabled>
        ☰
      </button>
      <div className="wordmark" aria-label="ARCEN">
        A&nbsp;R&nbsp;C&nbsp;E&nbsp;N
      </div>
      <div className="header-right">
        <span
          className={`status-dot ${status}`}
          role="img"
          aria-label={`stream ${status}`}
        />
        <button className="theme-toggle" aria-label="toggle theme" disabled title="dark only in v0.1">
          ◐
        </button>
      </div>
    </header>
  );
}

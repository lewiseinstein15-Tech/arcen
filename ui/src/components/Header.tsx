// ARCEN — top bar of the main area (v0.2 reference layout, ~64px, floats —
// no bottom border): hamburger on the left with the compact "+ New chat"
// (T-035), session chip + theme toggle on the right. The chip opens the
// sessions drawer (same store as Ctrl/Cmd+K).

import { useDrawerStore } from '../state/drawerStore';
import { useSidebarStore } from '../state/sidebarStore';
import { newChat } from '../state/chatActions';
import { ChevronDownIcon, HamburgerIcon, MoonIcon, PlusIcon } from './Icons';

export function Header() {
  const toggleSidebar = useSidebarStore((s) => s.toggle);
  const openSessions = useDrawerStore((s) => s.setOpen);
  return (
    <header className="topbar" data-testid="header">
      <div className="topbar-left">
        <button
          className="drawer-btn"
          aria-label="toggle sidebar"
          data-testid="drawer-btn"
          onClick={toggleSidebar}
        >
          <HamburgerIcon size={20} />
        </button>
        <button
          className="topbar-plus"
          aria-label="new chat"
          title="New chat"
          data-testid="topbar-plus"
          onClick={newChat}
        >
          <PlusIcon size={18} />
        </button>
      </div>
      <div className="topbar-right">
        <button
          className="session-chip"
          aria-label="open sessions"
          data-testid="session-chip"
          onClick={() => openSessions(true)}
        >
          <span className="chip-dot" aria-hidden="true" />
          <span className="chip-label">Agentic Engineer</span>
          <ChevronDownIcon size={16} className="chip-chev" />
        </button>
        <button className="theme-toggle" aria-label="toggle theme" disabled title="dark only in v0.1">
          <MoonIcon size={20} />
        </button>
      </div>
    </header>
  );
}

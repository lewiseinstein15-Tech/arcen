// ARCEN — Sidebar (v0.2 reference layout, ~256px, top to bottom):
//   logo block (triangle mark + two-line wordmark + breadcrumb) · + New chat
//   button (coral hairline, T-035) · nav list (Chat active — coral wash +
//   2px left border) · burnt-orange horizon gradient in the bottom third ·
//   status block (green dot + Online) · quote block (coral bar + italic
//   lines + attribution).
// <900px the sidebar becomes a fixed overlay behind the hamburger.

import { LogoMark } from './LogoMark';
import { ChatIcon, FolderIcon, GearIcon, PlusIcon, WrenchIcon } from './Icons';
import { useSidebarStore } from '../state/sidebarStore';
import { useUiStore } from '../state/uiStore';
import { newChat } from '../state/chatActions';

const NAV_ITEMS = [
  { label: 'Chat', Icon: ChatIcon, view: 'chat' as const },
  { label: 'Projects', Icon: FolderIcon, view: null }, // v0.2
  { label: 'Tools', Icon: WrenchIcon, view: null }, // v0.2
  { label: 'Settings', Icon: GearIcon, view: 'settings' as const },
];

export function Sidebar() {
  const open = useSidebarStore((s) => s.open);
  const setOpen = useSidebarStore((s) => s.setOpen);
  const view = useUiStore((s) => s.view);
  const setView = useUiStore((s) => s.setView);
  return (
    <>
      {open && (
        <div
          className="sidebar-overlay"
          data-testid="sidebar-overlay"
          onClick={() => setOpen(false)}
          aria-hidden="true"
        />
      )}
      <aside className="sidebar" data-testid="sidebar" aria-label="ARCEN">
        <div className="sidebar-inner">
          <div className="logo-block">
            <LogoMark height={40} className="logo-mark" />
            <div className="wordmark-2l">
              <span className="wm-1">Agentic</span>
              <span className="wm-2">Engineer</span>
            </div>
          </div>
          <div className="breadcrumb">
            Plan <span className="sep">&gt;</span> Build <span className="sep">&gt;</span> Execute
          </div>

          <button
            type="button"
            className="new-chat-btn"
            data-testid="new-chat-btn"
            onClick={() => {
              newChat();
              // close the overlay only on <900px — on desktop the sidebar
              // is a persistent column and must not collapse on use
              if (window.innerWidth < 900) setOpen(false);
            }}
          >
            <PlusIcon size={18} className="new-chat-plus" />
            <span>New chat</span>
          </button>

          <nav className="side-nav" aria-label="primary">
            {NAV_ITEMS.map(({ label, Icon, view: itemView }) => {
              const active = itemView === view;
              return (
                <button
                  key={label}
                  className={`nav-item ${active ? 'is-active' : ''}`}
                  aria-current={active ? 'page' : undefined}
                  disabled={itemView === null}
                  data-testid={`nav-${label.toLowerCase()}`}
                  onClick={() => {
                    if (itemView) setView(itemView);
                    if (window.innerWidth < 900) setOpen(false);
                  }}
                >
                  <Icon size={20} className="nav-icon" />
                  <span>{label}</span>
                </button>
              );
            })}
          </nav>

          <div className="sidebar-spacer" />

          <div className="side-status">
            <div className="status-line">
              <span className="online-dot" aria-hidden="true" />
              Online
            </div>
            <div className="status-sub">Your Agentic Engineer</div>
          </div>

          <div className="side-quote">
            <span className="quote-bar" aria-hidden="true" />
            <div>
              <p className="quote-line">
                plan like aider.
                <br />
                build like openhands.
                <br />
                verify like swe-agent.
              </p>
              <p className="quote-attr">— the ARCEN principle</p>
            </div>
          </div>
        </div>
        <div className="sidebar-deco" aria-hidden="true" />
      </aside>
    </>
  );
}

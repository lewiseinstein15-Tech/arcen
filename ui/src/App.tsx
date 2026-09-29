// ARCEN — App shell (v0.2 reference layout): Sidebar · main column
// (top bar · ChatView | SettingsView). The active session id comes from
// the session store. T-045: there is no hardcoded default — a fresh
// browser context resolves to a generated UUID before the first render
// (ensureActiveSession); T-035: "+ New chat" swaps it for another UUID.

import { ChatView } from './components/ChatView';
import { DrawerNav } from './components/Drawer';
import { Header } from './components/Header';
import { SettingsView } from './components/SettingsView';
import { Sidebar } from './components/Sidebar';
import { useSessionStore, ensureActiveSession } from './state/sessionStore';
import { useSidebarStore } from './state/sidebarStore';
import { useUiStore } from './state/uiStore';

export default function App() {
  const sidebarOpen = useSidebarStore((s) => s.open);
  const activeId = useSessionStore((s) => s.activeId);
  const view = useUiStore((s) => s.view);
  // T-045: no hardcoded fallback id. A fresh context (activeId null)
  // resolves to a generated UUID — idempotent, so StrictMode re-renders
  // converge on the same id and ChatView's key never churns.
  const sessionId = activeId ?? ensureActiveSession();
  return (
    <div className={`app ${sidebarOpen ? 'sidebar-open' : ''}`}>
      <Sidebar />
      <div className="main">
        <Header />
        {view === 'settings' ? <SettingsView key="settings" /> : <ChatView key={sessionId} sessionId={sessionId} />}
      </div>
      <DrawerNav />
    </div>
  );
}

// ARCEN — App shell (v0.2 reference layout): Sidebar · main column
// (top bar · ChatView | SettingsView). The active session id comes from
// the session store (T-035: "+ New chat" swaps it); 's-ui' remains the
// default chat.

import { ChatView } from './components/ChatView';
import { DrawerNav } from './components/Drawer';
import { Header } from './components/Header';
import { SettingsView } from './components/SettingsView';
import { Sidebar } from './components/Sidebar';
import { useSessionStore } from './state/sessionStore';
import { useSidebarStore } from './state/sidebarStore';
import { useUiStore } from './state/uiStore';

export default function App() {
  const sidebarOpen = useSidebarStore((s) => s.open);
  const activeId = useSessionStore((s) => s.activeId);
  const view = useUiStore((s) => s.view);
  const sessionId = activeId ?? 's-ui';
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

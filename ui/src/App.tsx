// ARCEN — App shell (v0.2 reference layout): Sidebar · main column
// (top bar · ChatView | SettingsView). The active session id comes from
// the session store (T-035: "+ New chat" swaps it); 's-ui' remains the
// default chat.

import { ChatView } from './components/ChatView';
import { DrawerNav } from './components/Drawer';
import { Header } from './components/Header';
import { Sidebar } from './components/Sidebar';
import { useSessionStore } from './state/sessionStore';
import { useSidebarStore } from './state/sidebarStore';

export default function App() {
  const sidebarOpen = useSidebarStore((s) => s.open);
  const activeId = useSessionStore((s) => s.activeId);
  const sessionId = activeId ?? 's-ui';
  return (
    <div className={`app ${sidebarOpen ? 'sidebar-open' : ''}`}>
      <Sidebar />
      <div className="main">
        <Header />
        <ChatView key={sessionId} sessionId={sessionId} />
      </div>
      <DrawerNav />
    </div>
  );
}

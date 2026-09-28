// ARCEN — App shell (v0.2 reference layout): Sidebar · main column
// (top bar · ChatView). The sessions drawer mounts portal-side (chip /
// Ctrl+K on desktop, bottom sheet on mobile).

import { ChatView } from './components/ChatView';
import { DrawerNav } from './components/Drawer';
import { Header } from './components/Header';
import { Sidebar } from './components/Sidebar';
import { useSidebarStore } from './state/sidebarStore';

export default function App() {
  const sidebarOpen = useSidebarStore((s) => s.open);
  return (
    <div className={`app ${sidebarOpen ? 'sidebar-open' : ''}`}>
      <Sidebar />
      <div className="main">
        <Header />
        <ChatView />
      </div>
      <DrawerNav />
    </div>
  );
}

// ARCEN — App shell (FRONTEND-SPEC Part 1): Drawer · Header · ChatView.

import { ChatView } from './components/ChatView';
import { DrawerNav } from './components/Drawer';
import { Header } from './components/Header';

export default function App() {
  return (
    <div className="app">
      <DrawerNav />
      <Header />
      <ChatView />
    </div>
  );
}

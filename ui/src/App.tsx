// ARCEN — App shell (FRONTEND-SPEC Part 1): Drawer · Header · ChatView.

import { ChatView } from './components/ChatView';
import { Header } from './components/Header';

export default function App() {
  return (
    <div className="app">
      <Header />
      <ChatView />
    </div>
  );
}

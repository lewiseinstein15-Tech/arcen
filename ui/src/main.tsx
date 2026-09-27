import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import './styles/tokens.css';
import './styles/global.css';

function Bootstrap() {
  return (
    <main style={{ padding: '24px' }}>
      <h1 style={{ fontSize: 14, fontWeight: 500 }}>ARCEN</h1>
      <p style={{ color: 'var(--text-2)' }}>Agentic reasoning. Code. Engineer.</p>
    </main>
  );
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <Bootstrap />
  </StrictMode>,
);

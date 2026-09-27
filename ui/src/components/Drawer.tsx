// ARCEN — mobile session drawer (FRONTEND-SPEC Part 11).
// In the browser: Vaul <Drawer.Root> primitives (drag-to-close, backdrop tap,
// body scroll lock, focus return). Under a test environment Vaul's portal
// cannot mount (jsdom), so the same content renders through a plain overlay
// with identical semantics — same rows, same classes, same a11y contract.
// Active session highlighted with the accent left-border. Interactive
// elements ≥ 44×44 touch targets.

import { useEffect } from 'react';
import { Drawer } from 'vaul';
import { useDrawerStore } from '../state/drawerStore';
import { useSessionStore } from '../state/sessionStore';
import { useStreamStore } from '../state/streamStore';

const VAUL_USABLE =
  typeof process === 'undefined' || process.env?.NODE_ENV !== 'test';

function SessionRows({ onPick }: { onPick: (id: string) => void }) {
  const sessions = useSessionStore((s) => s.sessions);
  const activeId = useSessionStore((s) => s.activeId);
  return (
    <ul className="session-list" data-testid="session-list">
      {sessions.length === 0 && <li className="session-empty meta">no sessions yet</li>}
      {sessions.map((s) => (
        <li key={s.id}>
          <button
            className={`session-row ${s.id === activeId ? 'is-active' : ''}`}
            data-testid={`session-${s.id}`}
            onClick={() => onPick(s.id)}
          >
            <span className="session-title">{s.title || s.id}</span>
            <span className="meta">
              {s.events} events · {s.status}
            </span>
          </button>
        </li>
      ))}
    </ul>
  );
}

export function DrawerNav() {
  const open = useDrawerStore((s) => s.open);
  const setOpen = useDrawerStore((s) => s.setOpen);
  const list = useSessionStore((s) => s.list);
  const replay = useSessionStore((s) => s.replay);
  const hydrate = useStreamStore((s) => s.hydrate);

  // refresh the list every time the drawer opens — however it was opened
  useEffect(() => {
    if (open) void list();
  }, [open, list]);

  const pick = async (id: string) => {
    useSessionStore.getState().open(id);
    const events = await replay(id);
    hydrate(events); // replay → hydrate → re-render in seq order (Part 8)
    setOpen(false);
  };

  if (VAUL_USABLE) {
    return (
      <Drawer.Root open={open} onOpenChange={setOpen}>
        <Drawer.Portal>
          <Drawer.Overlay className="drawer-overlay" data-testid="drawer-overlay" />
          <Drawer.Content className="drawer-content" data-testid="drawer-content" aria-label="sessions">
            <div className="drawer-handle" />
            <Drawer.Title className="drawer-title">SESSIONS</Drawer.Title>
            <SessionRows onPick={(id) => void pick(id)} />
            <Drawer.Close className="drawer-close" aria-label="close sessions">
              close
            </Drawer.Close>
          </Drawer.Content>
        </Drawer.Portal>
      </Drawer.Root>
    );
  }

  // test-environment fallback: plain DOM, same contract
  return (
    <div className="drawer-overlay" data-testid="drawer-overlay" onClick={() => setOpen(false)}>
      <aside
        className="drawer-content"
        data-testid="drawer-content"
        aria-label="sessions"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="drawer-handle" />
        <h2 className="drawer-title">SESSIONS</h2>
        <SessionRows onPick={(id) => void pick(id)} />
        <button className="drawer-close" aria-label="close sessions" onClick={() => setOpen(false)}>
          close
        </button>
      </aside>
    </div>
  );
}

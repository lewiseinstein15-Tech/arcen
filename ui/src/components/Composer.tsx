// ARCEN — Composer (FRONTEND-SPEC Part 10). Frozen key bindings:
//   Enter sends · Shift+Enter newline · ↑ edits last sent (empty composer)
//   / opens slash menu (empty) · ↑↓/Enter/Esc in menu · Esc blurs
//   Ctrl/Cmd+K opens the session drawer
// Send states: idle ↗ (disabled empty) · armed ↗ accent · streaming ■ stop.
// Auto-grow caps at 8 rows.

import { useEffect, useRef, useState, type KeyboardEvent } from 'react';
import TextareaAutosize from 'react-textarea-autosize';
import { useDrawerStore } from '../state/drawerStore';
import type { StreamStatus } from '../state/streamStore';

export const SLASH_COMMANDS: { cmd: string; help: string }[] = [
  { cmd: '/plan', help: 'show plan only' },
  { cmd: '/dry-run', help: 'stream, change none' },
  { cmd: '/model', help: 'switch provider' },
  { cmd: '/mcp', help: 'list MCP servers' },
  { cmd: '/clear', help: 'new session' },
];

interface ComposerProps {
  value: string;
  onChange: (v: string) => void;
  onSend: (text: string) => void;
  onStop?: () => void;
  status: StreamStatus;
}

export function Composer({ value, onChange, onSend, onStop, status }: ComposerProps) {
  const ref = useRef<HTMLTextAreaElement>(null);
  const [menuIndex, setMenuIndex] = useState(0);
  const [lastSent, setLastSent] = useState('');
  const setDrawerOpen = useDrawerStore((s) => s.setOpen);

  const menuOpen = value.startsWith('/');
  const menuItems = menuOpen
    ? SLASH_COMMANDS.filter((c) => c.cmd.startsWith(value.split(' ')[0]))
    : [];
  const streaming = status === 'streaming';
  const canSend = value.trim().length > 0 && !streaming;

  useEffect(() => setMenuIndex(0), [value]);

  const send = () => {
    if (!canSend) return;
    setLastSent(value);
    onSend(value);
    onChange('');
  };

  const insertCommand = (cmd: string) => {
    onChange(cmd + ' ');
    ref.current?.focus();
  };

  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    // slash menu navigation takes precedence while open
    if (menuOpen && menuItems.length > 0) {
      if (e.key === 'ArrowDown') {
        e.preventDefault();
        setMenuIndex((i) => (i + 1) % menuItems.length);
        return;
      }
      if (e.key === 'ArrowUp') {
        e.preventDefault();
        setMenuIndex((i) => (i - 1 + menuItems.length) % menuItems.length);
        return;
      }
      if (e.key === 'Enter') {
        e.preventDefault();
        insertCommand(menuItems[menuIndex].cmd); // insert, never send
        return;
      }
      if (e.key === 'Escape') {
        e.preventDefault();
        onChange(''); // close menu
        return;
      }
    }
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault(); // Enter sends, Shift+Enter newlines
      send();
      return;
    }
    if (e.key === 'Escape' && !menuOpen) {
      e.currentTarget.blur(); // Esc blurs the composer
      return;
    }
    if (e.key === 'ArrowUp' && value.length === 0 && lastSent) {
      e.preventDefault();
      onChange(lastSent); // edit last sent message
      return;
    }
  };

  const onGlobalKey = (e: globalThis.KeyboardEvent) => {
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
      e.preventDefault();
      setDrawerOpen(true); // Ctrl/Cmd+K opens the session drawer, anywhere
    }
  };

  useEffect(() => {
    window.addEventListener('keydown', onGlobalKey);
    return () => window.removeEventListener('keydown', onGlobalKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="composer" data-testid="composer">
      {menuOpen && menuItems.length > 0 && (
        <ul className="slash-menu" role="listbox" aria-label="slash commands" data-testid="slash-menu">
          {menuItems.map((c, i) => (
            <li
              key={c.cmd}
              role="option"
              aria-selected={i === menuIndex}
              className={i === menuIndex ? 'is-selected' : ''}
              onMouseDown={(e) => {
                e.preventDefault();
                insertCommand(c.cmd);
              }}
            >
              <span className="cmd">{c.cmd}</span>
              <span className="meta">{c.help}</span>
            </li>
          ))}
        </ul>
      )}
      <TextareaAutosize
        ref={ref}
        className="composer-input"
        placeholder="describe the task…"
        value={value}
        minRows={1}
        maxRows={8}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={onKeyDown}
        aria-label="composer"
        data-testid="composer-input"
      />
      <button
        className={`send-btn ${canSend ? 'armed' : ''}`}
        aria-label={streaming ? 'stop' : 'send'}
        data-testid="send-btn"
        disabled={!streaming && !canSend}
        onClick={() => {
          if (streaming) onStop?.();
          else send();
        }}
      >
        {streaming ? '■' : '↗'}
      </button>
    </div>
  );
}

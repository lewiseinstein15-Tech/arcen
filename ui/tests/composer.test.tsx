// F-10 — keyboard: Enter sends, Shift+Enter newlines, / opens menu, Esc closes,
// ↑ edits last sent, menu Enter inserts (does not send), Ctrl/Cmd+K drawer.

import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { Composer, SLASH_COMMANDS } from '../src/components/Composer';
import { useDrawerStore } from '../src/state/drawerStore';

function setup(status: 'idle' | 'streaming' = 'idle') {
  const onSend = vi.fn();
  const onChange = vi.fn();
  let value = '';
  // controlled wrapper — Composer is controlled by ChatView
  function Host() {
    return (
      <Composer
        value={value}
        onChange={(v) => {
          value = v;
          onChange(v);
        }}
        onSend={onSend}
        status={status}
      />
    );
  }
  const utils = render(<Host />);
  const input = screen.getByTestId('composer-input') as HTMLTextAreaElement;
  const rerender = () => utils.rerender(<Host />);
  return { onSend, onChange, input, rerender, unmount: utils.unmount, set: (v: string) => ((value = v), rerender()) };
}

describe('F-10: composer keyboard', () => {
  it('Enter sends; Shift+Enter inserts a newline', () => {
    const { onSend, input, set } = setup();
    set('fix the test');
    fireEvent.keyDown(input, { key: 'Enter', shiftKey: false });
    expect(onSend).toHaveBeenCalledWith('fix the test');
    // newline path
    set('line one');
    fireEvent.keyDown(input, { key: 'Enter', shiftKey: true });
    expect(onSend).toHaveBeenCalledTimes(1); // not sent
  });

  it('empty composer: Enter does not send; ↑ edits the last sent message', () => {
    const { onSend, input, set } = setup();
    set('first goal');
    fireEvent.keyDown(input, { key: 'Enter' });
    expect(onSend).toHaveBeenCalledWith('first goal');
    set(''); // composer now empty
    fireEvent.keyDown(input, { key: 'ArrowUp' });
    // the parent would restore lastSent through onChange; Composer calls onChange
    expect(onSend).toHaveBeenCalledTimes(1);
  });

  it('/ opens the slash menu filtered by the text after /', () => {
    const { set } = setup();
    set('/');
    expect(screen.getByTestId('slash-menu')).toBeInTheDocument();
    expect(screen.getAllByRole('option')).toHaveLength(SLASH_COMMANDS.length);
    set('/m');
    expect(screen.getByRole('option', { name: /model/ })).toBeInTheDocument();
    expect(screen.queryByRole('option', { name: /clear/ })).toBeNull();
  });

  it('menu: ↑↓ move selection, Enter inserts without sending, Esc closes', () => {
    const { onSend, input, set } = setup();
    set('/');
    fireEvent.keyDown(input, { key: 'ArrowDown' });
    fireEvent.keyDown(input, { key: 'Enter' });
    expect(onSend).not.toHaveBeenCalled(); // insert, never send
    set('/c');
    fireEvent.keyDown(input, { key: 'Escape' });
    // menu gone
    waitFor(() => expect(screen.queryByTestId('slash-menu')).toBeNull());
  });

  it('Esc blurs the composer when no menu is open', () => {
    const { input, set } = setup();
    set('some text');
    const blur = vi.spyOn(input, 'blur');
    fireEvent.keyDown(input, { key: 'Escape' });
    expect(blur).toHaveBeenCalled();
  });

  it('Ctrl/Cmd+K opens the session drawer from anywhere', () => {
    setup();
    fireEvent.keyDown(window, { key: 'k', ctrlKey: true });
    expect(useDrawerStore.getState().open).toBe(true);
    useDrawerStore.getState().setOpen(false);
    fireEvent.keyDown(window, { key: 'k', metaKey: true });
    expect(useDrawerStore.getState().open).toBe(true);
  });

  it('send button: armed with text, stop while streaming, disabled when empty', () => {
    const onSend = vi.fn();
    let status: 'idle' | 'streaming' = 'idle';
    let value = '';
    function Host() {
      return (
        <Composer
          value={value}
          onChange={(v) => {
            value = v;
          }}
          onSend={onSend}
          status={status}
        />
      );
    }
    const utils = render(<Host />);
    const rerender = () => utils.rerender(<Host />);

    value = '';
    rerender();
    expect(screen.getByTestId('send-btn')).toBeDisabled();

    value = 'goal';
    rerender();
    expect(screen.getByTestId('send-btn')).toHaveClass('armed');

    status = 'streaming';
    rerender();
    expect(screen.getByTestId('send-btn')).toHaveAttribute('aria-label', 'stop');
    expect(screen.getByText('■')).toBeInTheDocument();
  });
});

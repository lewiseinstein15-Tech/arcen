// ARCEN — top-level view state (T-036): the main column shows either the
// chat or the Settings view. The sidebar nav drives it.

import { create } from 'zustand';

export type View = 'chat' | 'settings';

interface UiState {
  view: View;
  setView: (view: View) => void;
}

export const useUiStore = create<UiState>((set) => ({
  view: 'chat',
  setView: (view) => set({ view }),
}));

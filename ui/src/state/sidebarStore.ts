// ARCEN — sidebar visibility (v0.2 layout). One boolean drives both modes:
// desktop ≥900px shows/hides the 256px column; <900px it reveals the
// sidebar as a fixed overlay behind the hamburger.

import { create } from 'zustand';

interface SidebarState {
  open: boolean;
  setOpen: (open: boolean) => void;
  toggle: () => void;
}

export const useSidebarStore = create<SidebarState>((set) => ({
  open: true,
  setOpen: (open) => set({ open }),
  toggle: () => set((s) => ({ open: !s.open })),
}));

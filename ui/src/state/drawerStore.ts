// ARCEN — drawer store, deliberately ephemeral (Part 9): a refresh closes it.

import { create } from 'zustand';

interface DrawerStore {
  open: boolean;
  setOpen: (open: boolean) => void;
}

export const useDrawerStore = create<DrawerStore>((set) => ({
  open: false,
  setOpen: (open) => set({ open }),
}));

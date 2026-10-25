/** Estado global de la interfaz (Zustand): tema y menú lateral móvil. */
import { create } from "zustand";
import { persist } from "zustand/middleware";

export type Theme = "light" | "dark" | "system";

interface UiState {
  theme: Theme;
  sidebarOpen: boolean;
  setTheme: (theme: Theme) => void;
  setSidebarOpen: (open: boolean) => void;
}

export function applyTheme(theme: Theme): void {
  const dark = theme === "dark" || (theme === "system" && window.matchMedia?.("(prefers-color-scheme: dark)").matches);
  document.documentElement.classList.toggle("dark", !!dark);
}

export const useUiStore = create<UiState>()(
  persist(
    (set) => ({
      theme: "system",
      sidebarOpen: false,
      setTheme: (theme) => {
        applyTheme(theme);
        set({ theme });
      },
      setSidebarOpen: (sidebarOpen) => set({ sidebarOpen }),
    }),
    { name: "ui-store", partialize: (state) => ({ theme: state.theme }) },
  ),
);

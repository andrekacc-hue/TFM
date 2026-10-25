import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import App from "./App";
import { applyTheme, useUiStore } from "./stores/ui-store";
import "./styles/globals.css";

applyTheme(useUiStore.getState().theme);
// Si el tema es "sistema", seguir los cambios del sistema operativo en vivo
window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => {
  if (useUiStore.getState().theme === "system") applyTheme("system");
});

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);

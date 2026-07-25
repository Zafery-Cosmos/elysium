import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import { bootstrapSettings } from "./stores/settings";
import "./index.css";

// Applique densité / thème / animations au document avant le premier rendu.
bootstrapSettings();

const container = document.getElementById("root");
if (container === null) {
  throw new Error("Élément racine #root introuvable.");
}

createRoot(container).render(
  <StrictMode>
    <App />
  </StrictMode>,
);

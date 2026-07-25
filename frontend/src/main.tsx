import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import { bootstrapSettings, useSettingsStore } from "./stores/settings";
import "./index.css";

// Applique densité / thème / animations au document avant le premier rendu.
bootstrapSettings();

// Récupère (au mieux) les réglages exposés par le moteur et les fusionne.
void useSettingsStore.getState().syncFromEngine();

// Désactive le menu contextuel (clic droit) : Elysium est une application
// desktop, pas une page web — le menu natif du navigateur n'a pas sa place.
window.addEventListener("contextmenu", (e) => {
  e.preventDefault();
});

const container = document.getElementById("root");
if (container === null) {
  throw new Error("Élément racine #root introuvable.");
}

createRoot(container).render(
  <StrictMode>
    <App />
  </StrictMode>,
);

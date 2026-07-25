import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import { bootstrapSettings } from "./stores/settings";
import "./index.css";

// Applique densité / thème / animations au document avant le premier rendu.
bootstrapSettings();

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

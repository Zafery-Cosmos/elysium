import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { OnboardingTour } from "./OnboardingTour";
import { TOUR_STEPS } from "./tourSteps";
import { useSettingsStore } from "../../stores/settings";
import { useUiStore } from "../../stores/ui";

beforeEach(() => {
  // Mouvement réduit : les scènes sautent à leur état final, sans minuterie.
  useSettingsStore.setState({ language: "fr", motion: "reduced" });
  useUiStore.setState({ tourDone: false });
});
afterEach(cleanup);

const next = (): void => {
  fireEvent.click(screen.getByRole("button", { name: /^(Suivant|Commencer)$/ }));
};

describe("OnboardingTour", () => {
  it("opens on the first step with a French dialog and a skip button", () => {
    render(<OnboardingTour />);
    expect(screen.getByRole("dialog", { name: "Tutoriel d'Elysium" })).toBeTruthy();
    expect(screen.getByText(`Étape 1 sur ${String(TOUR_STEPS.length)}`)).toBeTruthy();
    expect(screen.getByRole("button", { name: "Passer le tutoriel" })).toBeTruthy();
    expect(screen.getByText(/rien n'est envoyé, rien n'est écrit/)).toBeTruthy();
  });

  it("skipping marks the tutorial as done", () => {
    render(<OnboardingTour />);
    fireEvent.click(screen.getByRole("button", { name: "Passer le tutoriel" }));
    expect(useUiStore.getState().tourDone).toBe(true);
  });

  it("Escape closes it", () => {
    render(<OnboardingTour />);
    fireEvent.keyDown(document, { key: "Escape" });
    expect(useUiStore.getState().tourDone).toBe(true);
  });

  it("walks through every step and finishes with « Commencer »", () => {
    render(<OnboardingTour />);
    for (let i = 1; i < TOUR_STEPS.length; i += 1) {
      next();
      expect(screen.getByText(`Étape ${String(i + 1)} sur ${String(TOUR_STEPS.length)}`)).toBeTruthy();
    }
    expect(useUiStore.getState().tourDone).toBe(false);
    next(); // « Commencer »
    expect(useUiStore.getState().tourDone).toBe(true);
  });

  it("arrow keys move between steps", () => {
    render(<OnboardingTour />);
    fireEvent.keyDown(document, { key: "ArrowRight" });
    expect(screen.getByText(`Étape 2 sur ${String(TOUR_STEPS.length)}`)).toBeTruthy();
    fireEvent.keyDown(document, { key: "ArrowLeft" });
    expect(screen.getByText(`Étape 1 sur ${String(TOUR_STEPS.length)}`)).toBeTruthy();
  });

  it("fake chat: clicking Envoyer shows the conversation and marks the step as tried", () => {
    render(<OnboardingTour />);
    next(); // étape 1 : fausse conversation
    const idea = "Je veux une application pour réserver des restaurants.";
    // Avant l'envoi, la phrase n'est que dans le champ de saisie : pas encore de bulle ni de réponse.
    expect(screen.getAllByText(idea)).toHaveLength(1);
    expect(screen.queryByText(/Elle servira à qui/)).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Envoyer" }));
    expect(screen.getAllByText(idea)).toHaveLength(1); // champ vidé, bulle affichée
    expect(screen.getByText(/Elle servira à qui/)).toBeTruthy();
    expect(screen.getByText(/Elle servira à qui/)).toBeTruthy();
    expect(screen.getByText("Bien joué.")).toBeTruthy();
  });

  it("fake plan: approving runs the tasks to completion, refusing removes them", () => {
    render(<OnboardingTour />);
    for (let i = 0; i < 3; i += 1) next(); // étape 3 : plan
    fireEvent.click(screen.getByRole("button", { name: "Valider le plan" }));
    expect(screen.getAllByText("Terminée")).toHaveLength(4);
    fireEvent.click(screen.getByRole("button", { name: /Rejouer/ }));
    fireEvent.click(screen.getByRole("button", { name: "Refuser" }));
    expect(screen.getByText("Plan refusé : rien n'a démarré.")).toBeTruthy();
  });

  it("fake diff: apply then undo, nothing real is touched", () => {
    render(<OnboardingTour />);
    for (let i = 0; i < 4; i += 1) next(); // étape 4 : diff
    fireEvent.click(screen.getByRole("button", { name: "Appliquer" }));
    expect(screen.getByText(/Écrit sur le disque \(exemple\)/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Annuler le changement" }));
    expect(screen.getByText("Fichier d'origine restauré à l'octet près.")).toBeTruthy();
    expect(screen.getByText("Bien joué.")).toBeTruthy();
  });

  it("model step lists subscription (OAuth) before API before local", () => {
    render(<OnboardingTour />);
    for (let i = 0; i < 5; i += 1) next(); // étape 5 : modèles
    const titles = screen.getAllByRole("heading", { level: 4 }).map((h) => h.textContent);
    expect(titles).toEqual(["Abonnement (OAuth)", "API (clé)", "Local"]);
    fireEvent.click(screen.getByRole("button", { name: "Claude Code" }));
    expect(screen.getByText("Sélectionné : Claude Code")).toBeTruthy();
  });

  it("is translated: English labels when the language is English", () => {
    act(() => {
      useSettingsStore.setState({ language: "en" });
    });
    render(<OnboardingTour />);
    expect(screen.getByRole("dialog", { name: "Elysium tutorial" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Skip tutorial" })).toBeTruthy();
  });
});

/**
 * Internationalisation légère, typée, sans dépendance externe.
 *
 * `useT()` lit la langue dans le store des réglages : tout composant qui
 * l'utilise se re-rend automatiquement au changement de langue (bascule
 * en direct depuis Réglages › Général). Défaut : français.
 */

import { useMemo } from "react";
import { useSettingsStore, type Language } from "../stores/settings";
import { en, es, fr, type MessageKey } from "./dictionaries";

const DICTS: Record<Language, Record<MessageKey, string>> = { fr, en, es };

export type TFunction = (
  key: MessageKey,
  params?: Record<string, string | number>,
) => string;

export function translate(
  lang: Language,
  key: MessageKey,
  params?: Record<string, string | number>,
): string {
  const dict = DICTS[lang] ?? fr;
  let value = dict[key] ?? fr[key];
  if (params !== undefined) {
    for (const [name, raw] of Object.entries(params)) {
      value = value.replaceAll(`{${name}}`, String(raw));
    }
  }
  return value;
}

/** Hook principal : renvoie une fonction `t` liée à la langue active. */
export function useT(): TFunction {
  const lang = useSettingsStore((s) => s.language);
  return useMemo<TFunction>(
    () => (key, params) => translate(lang, key, params),
    [lang],
  );
}

export const LANGUAGE_OPTIONS: Array<{ value: Language; label: string }> = [
  { value: "fr", label: "Français" },
  { value: "en", label: "English" },
  { value: "es", label: "Español" },
];

export type { MessageKey };

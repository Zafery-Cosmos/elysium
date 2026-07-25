import { useEffect, useState } from "react";
import { useSettingsStore } from "../stores/settings";

/**
 * Indique si le mouvement doit être réduit, en combinant le réglage
 * « Animations » d'Elysium et la préférence système :
 * - « reduced » → toujours réduit ;
 * - « on » → jamais réduit (l'utilisateur force les animations) ;
 * - « auto » → suit `prefers-reduced-motion` du système.
 */
export function usePrefersReducedMotion(): boolean {
  const motion = useSettingsStore((s) => s.motion);
  const [systemReduced, setSystemReduced] = useState(false);

  useEffect(() => {
    if (typeof window === "undefined" || window.matchMedia === undefined) {
      return;
    }
    const query = window.matchMedia("(prefers-reduced-motion: reduce)");
    setSystemReduced(query.matches);
    const onChange = (e: MediaQueryListEvent): void => {
      setSystemReduced(e.matches);
    };
    query.addEventListener("change", onChange);
    return () => {
      query.removeEventListener("change", onChange);
    };
  }, []);

  if (motion === "reduced") return true;
  if (motion === "on") return false;
  return systemReduced;
}

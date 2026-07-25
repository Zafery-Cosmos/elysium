import { Outlet, useLocation } from "react-router-dom";
import { Sidebar } from "./Sidebar";
import { UpdatePrompt } from "../UpdatePrompt";

export function AppShell() {
  const { pathname } = useLocation();
  return (
    <div className="flex h-dvh overflow-hidden bg-paper text-ink">
      <Sidebar />
      {/* Keyed on the route: remount + fondu léger à chaque navigation. */}
      <main
        key={pathname}
        className="flex min-w-0 flex-1 animate-fade-in flex-col overflow-hidden"
      >
        <Outlet />
      </main>
      {/* Popup de mise à jour intégrée (app Tauri uniquement). */}
      <UpdatePrompt />
    </div>
  );
}

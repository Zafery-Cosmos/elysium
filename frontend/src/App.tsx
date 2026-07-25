import { HashRouter, Navigate, Route, Routes, useParams } from "react-router-dom";
import { AppShell } from "./components/layout/AppShell";
import { Home } from "./pages/Home";
import { Chat } from "./pages/Chat";
import { Dashboard } from "./pages/Dashboard";
import { Projects } from "./pages/Projects";
import { Agents } from "./pages/Agents";
import { Models } from "./pages/Models";
import { Settings } from "./pages/Settings";

/** Ancienne URL /projects/:id → nouvelle expérience de chat. */
function LegacyProjectRedirect() {
  const { id } = useParams<{ id: string }>();
  if (id === undefined) return <Navigate to="/" replace />;
  return <Navigate to={`/chat/${encodeURIComponent(id)}`} replace />;
}

/**
 * HashRouter : fonctionne à l'identique en dev navigateur et dans la
 * webview Tauri (pas de serveur pour réécrire les URL en production).
 */
export function App() {
  return (
    <HashRouter>
      <Routes>
        <Route element={<AppShell />}>
          <Route index element={<Home />} />
          <Route path="chat/:id" element={<Chat />} />
          <Route path="dashboard" element={<Dashboard />} />
          <Route path="projects" element={<Projects />} />
          <Route path="projects/:id" element={<LegacyProjectRedirect />} />
          <Route path="agents" element={<Agents />} />
          <Route path="models" element={<Models />} />
          <Route path="settings" element={<Settings />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
    </HashRouter>
  );
}

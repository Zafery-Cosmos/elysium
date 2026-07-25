import { lazy, Suspense } from "react";
import { HashRouter, Navigate, Route, Routes, useParams } from "react-router-dom";
import { AppShell } from "./components/layout/AppShell";
import { Spinner } from "./components/ui/Spinner";
import { Home } from "./pages/Home";
import { Chat } from "./pages/Chat";

/**
 * Les surfaces lourdes sont chargées à la demande : la surface de chat
 * (accueil + fil) reste légère au démarrage. Repli minimal pendant le chargement.
 */
const Dashboard = lazy(() =>
  import("./pages/Dashboard").then((m) => ({ default: m.Dashboard })),
);
const Projects = lazy(() =>
  import("./pages/Projects").then((m) => ({ default: m.Projects })),
);
const Agents = lazy(() =>
  import("./pages/Agents").then((m) => ({ default: m.Agents })),
);
const Models = lazy(() =>
  import("./pages/Models").then((m) => ({ default: m.Models })),
);
const Mcp = lazy(() => import("./pages/Mcp").then((m) => ({ default: m.Mcp })));
const Settings = lazy(() =>
  import("./pages/Settings").then((m) => ({ default: m.Settings })),
);

function RouteFallback() {
  return (
    <div
      className="flex h-full items-center justify-center text-neutral"
      role="status"
    >
      <Spinner />
    </div>
  );
}

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
          <Route
            path="dashboard"
            element={
              <Suspense fallback={<RouteFallback />}>
                <Dashboard />
              </Suspense>
            }
          />
          <Route
            path="projects"
            element={
              <Suspense fallback={<RouteFallback />}>
                <Projects />
              </Suspense>
            }
          />
          <Route path="projects/:id" element={<LegacyProjectRedirect />} />
          <Route
            path="agents"
            element={
              <Suspense fallback={<RouteFallback />}>
                <Agents />
              </Suspense>
            }
          />
          <Route
            path="models"
            element={
              <Suspense fallback={<RouteFallback />}>
                <Models />
              </Suspense>
            }
          />
          <Route
            path="mcp"
            element={
              <Suspense fallback={<RouteFallback />}>
                <Mcp />
              </Suspense>
            }
          />
          <Route
            path="settings"
            element={
              <Suspense fallback={<RouteFallback />}>
                <Settings />
              </Suspense>
            }
          />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
    </HashRouter>
  );
}

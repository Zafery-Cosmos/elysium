import { lazy, Suspense, useEffect } from "react";
import {
  HashRouter,
  Navigate,
  Route,
  Routes,
  useLocation,
  useNavigate,
  useParams,
} from "react-router-dom";
import { engine } from "./services/engine";
import { useSettingsStore } from "./stores/settings";
import { AppShell } from "./components/layout/AppShell";
import { Spinner } from "./components/ui/Spinner";
import { Home } from "./pages/Home";
import { Chat } from "./pages/Chat";
import { Welcome } from "./pages/Welcome";
import { useUiStore } from "./stores/ui";

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
const Admin = lazy(() => import("./pages/Admin").then((m) => ({ default: m.Admin })));
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
/** Une seule vérification par lancement de l'application. */
let resumeChecked = false;

/**
 * Réglage « Reprendre la dernière conversation » : au lancement, si on arrive
 * sur l'accueil et que le dernier projet existe encore, on le rouvre.
 */
function ResumeLastConversation() {
  const navigate = useNavigate();
  const { pathname } = useLocation();
  useEffect(() => {
    if (resumeChecked) return;
    resumeChecked = true;
    const { lastProjectId, setLastProject } = useUiStore.getState();
    if (!useSettingsStore.getState().resumeLastConversation) return;
    if (lastProjectId === null || pathname !== "/") return;
    engine
      .getProject(lastProjectId)
      .then((project) => {
        // « Supprimer » archive le projet : il existe encore côté moteur.
        if (project.status === "archived") {
          setLastProject(null);
          return;
        }
        navigate(`/chat/${encodeURIComponent(lastProjectId)}`, { replace: true });
      })
      .catch(() => {
        setLastProject(null); // projet supprimé ou moteur injoignable
      });
  }, [navigate, pathname]);
  return null;
}

export function App() {
  const onboardingDone = useUiStore((s) => s.onboardingDone);
  if (!onboardingDone) return <Welcome />;
  return (
    <HashRouter>
      <ResumeLastConversation />
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
            path="admin"
            element={
              <Suspense fallback={<RouteFallback />}>
                <Admin />
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

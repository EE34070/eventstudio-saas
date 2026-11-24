import { Suspense, useEffect, useState } from "react";
import { BrowserRouter, Navigate, Route, Routes, useParams } from "react-router-dom";
import { ClerkProvider, Show, SignIn, useAuth } from "@clerk/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { SessionProvider, useSession } from "@/core/session/SessionProvider";
import { AppShell } from "@/core/layout/AppShell";
import { frontModules } from "@/core/modules/registry";
import { api, configureApi } from "@/core/api/client";

const queryClient = new QueryClient({ defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: false } } });
const EXTERNAL = new Set(["client", "partner", "organizer"]);

export function ModuleRoutes() {
  const { session, hasModule } = useSession();

  // Comptes externes (mariés, prestataires…) : l'espace dédié du module qui les a invités
  if (EXTERNAL.has(session.org.role)) {
    const portal = frontModules.find((m) => m.portal?.roles.includes(session.org.role));
    if (!portal?.portal) return <div className="center">Aucun espace disponible pour ce compte.</div>;
    const Portal = portal.portal.component;
    return <Suspense fallback={<div className="center">…</div>}><Portal /></Suspense>;
  }

  const home = session.branding.home_path ?? "/events";
  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route index element={<Navigate to={home} replace />} />
        {frontModules
          .filter((m) => hasModule(m.key)) // une route de module non souscrit n'existe tout simplement pas
          .flatMap((m) =>
            m.routes.map((r) => (
              <Route key={`${m.key}${r.path}`} path={r.path}
                     element={<Suspense fallback={<div className="center">…</div>}><r.component /></Suspense>} />
            )),
          )}
        <Route path="*" element={<div className="center">Page introuvable ou module non inclus dans votre offre.</div>} />
      </Route>
    </Routes>
  );
}

/** Lien d'invitation (mariés, prestataires) : connexion ou création de compte, puis rattachement. */
function Invitation() {
  const { token = "" } = useParams();
  const [state, setState] = useState<"working" | "error">("working");
  const [message, setMessage] = useState("");
  useEffect(() => {
    api<{ org_id: string }>("/invitations/accept", { method: "POST", body: JSON.stringify({ token }) })
      .then((r) => {
        try { localStorage.setItem("activeOrg", r.org_id); } catch { /* sans stockage : première org */ }
        window.location.replace("/");
      })
      .catch((e: Error) => { setState("error"); setMessage(e.message); });
  }, [token]);
  return <div className="center">{state === "working" ? "Ouverture de votre espace…" : message}</div>;
}

function SignedIn() {
  const { getToken } = useAuth();
  configureApi({ getToken: () => getToken() });
  return (
    <Routes>
      <Route path="/invitation/:token" element={<Invitation />} />
      <Route path="*" element={<SessionProvider><ModuleRoutes /></SessionProvider>} />
    </Routes>
  );
}

export default function App() {
  return (
    <ClerkProvider publishableKey={import.meta.env.VITE_CLERK_PUBLISHABLE_KEY}>
      <QueryClientProvider client={queryClient}>
        <BrowserRouter>
          <Show when="signed-out">
            <div className="center"><SignIn routing="hash" /></div>
          </Show>
          <Show when="signed-in">
            <SignedIn />
          </Show>
        </BrowserRouter>
      </QueryClientProvider>
    </ClerkProvider>
  );
}

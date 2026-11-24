import { Suspense } from "react";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { ClerkProvider, Show, SignIn } from "@clerk/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { SessionProvider, useSession } from "@/core/session/SessionProvider";
import { AppShell } from "@/core/layout/AppShell";
import { frontModules } from "@/core/modules/registry";

const queryClient = new QueryClient({ defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: false } } });

function ModuleRoutes() {
  const { hasModule } = useSession();
  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route index element={<Navigate to="/events" replace />} />
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

export default function App() {
  return (
    <ClerkProvider publishableKey={import.meta.env.VITE_CLERK_PUBLISHABLE_KEY}>
      <QueryClientProvider client={queryClient}>
        <BrowserRouter>
          <Show when="signed-out">
            <div className="center"><SignIn routing="hash" /></div>
          </Show>
          <Show when="signed-in">
            <SessionProvider>
              <ModuleRoutes />
            </SessionProvider>
          </Show>
        </BrowserRouter>
      </QueryClientProvider>
    </ClerkProvider>
  );
}

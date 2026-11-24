import { Suspense, useState } from "react";
import { MemoryRouter, Navigate, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { setApiMock } from "@/core/api/client";
import { FocusShell } from "@/core/layout/FocusShell";
import { frontModules } from "@/core/modules/registry";
import { StaticSessionProvider, type Session } from "@/core/session/SessionProvider";
import { mockApi } from "./mockServer";

/** MODE DÉMO : vrais écrans du produit, faux serveur en mémoire, données fictives. */
setApiMock(mockApi);

const BRANDING: Session["branding"] = {
  app_name: "Manon Jeanjean", layout: "focus", home_path: "/mariages",
  primary_color: "#1F3D2B", background: "#F2F1EB", surface: "#FAF9F5", ink: "#4b5c4c", muted: "#6b7a63",
  line: "#cdd6c6", soft: "#a9c0ac", alert: "#9a3b2e", font_display: "Cormorant Garamond", font_body: "Montserrat",
};
const base = { user_id: "demo", plan: "pro", subscription_status: "active", limits: {}, branding: BRANDING };
const ADMIN: Session = { ...base, org: { id: "manon", name: "Manon Jeanjean Wedding Planner", role: "owner" },
  orgs: [{ id: "manon", name: "Manon Jeanjean Wedding Planner", role: "owner" }],
  modules: [{ key: "wedding_planner", name: "Wedding planner", category: "metiers", status: "beta", can_write: true }] };
const COUPLE: Session = { ...base, org: { id: "manon", name: "Manon Jeanjean Wedding Planner", role: "client" }, orgs: [], modules: [] };

const qc = new QueryClient({ defaultOptions: { queries: { retry: 0, refetchOnWindowFocus: false } } });
const wpMod = frontModules.find((m) => m.key === "wedding_planner")!;
const Couple = wpMod.portal!.component;

export default function DemoApp() {
  const [space, setSpace] = useState<"admin" | "couple">("admin");
  return (
    <QueryClientProvider client={qc}>
      <div className="demo-bar">
        <b>Démo</b><span>Vrai code de l'application, données fictives, rien n'est enregistré. Espace :</span>
        <button aria-pressed={space === "admin"} onClick={() => setSpace("admin")}>Manon</button>
        <button aria-pressed={space === "couple"} onClick={() => { setSpace("couple"); qc.invalidateQueries(); }}>Mariés (Annie &amp; Patrick)</button>
      </div>
      {space === "admin" ? (
        <StaticSessionProvider session={ADMIN}>
          <MemoryRouter initialEntries={["/mariages"]}>
            <Routes>
              <Route element={<FocusShell />}>
                <Route index element={<Navigate to="/mariages" replace />} />
                {wpMod.routes.map((r) => (
                  <Route key={r.path} path={r.path} element={<Suspense fallback={null}><r.component /></Suspense>} />
                ))}
              </Route>
            </Routes>
          </MemoryRouter>
        </StaticSessionProvider>
      ) : (
        <StaticSessionProvider session={COUPLE}>
          <MemoryRouter><Suspense fallback={null}><Couple /></Suspense></MemoryRouter>
        </StaticSessionProvider>
      )}
    </QueryClientProvider>
  );
}

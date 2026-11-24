import { createContext, useContext, type ReactNode } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useAuth } from "@clerk/react";
import { api, configureApi, setActiveOrg, storedOrg } from "@/core/api/client";

export type ModuleInfo = { key: string; name: string; category: string; status: string; can_write: boolean };
export type OrgSummary = { id: string; name: string; role: string };
export type Session = {
  user_id: string;
  org: OrgSummary;
  orgs: OrgSummary[];
  plan: string;
  subscription_status: string;
  limits: Record<string, number>;
  modules: ModuleInfo[];
  branding: Branding;
};

/** Image de marque de l'organisation (marque blanche) : rien n'est codé en dur dans le produit. */
export type Branding = {
  app_name?: string;
  logo_url?: string;
  primary_color?: string;
  background?: string;
  surface?: string;
  ink?: string;
  muted?: string;
  line?: string;
  soft?: string;
  alert?: string;
  font_display?: string;
  font_body?: string;
  /** "focus" : en-tête horizontal sans barre latérale (organisation mono-métier) */
  layout?: "sidebar" | "focus";
  home_path?: string;
};

type Ctx = {
  session: Session;
  hasModule: (key: string) => boolean;
  canWrite: (key: string) => boolean;
  switchOrg: (orgId: string) => void;
};

const SessionContext = createContext<Ctx | null>(null);

setActiveOrg(storedOrg()); // organisation choisie lors de la dernière visite

export function SessionProvider({ children }: { children: ReactNode }) {
  const { getToken, isSignedIn } = useAuth();
  const qc = useQueryClient();

  // Configuré pendant le rendu (affectation idempotente) pour être prêt avant la 1re requête
  configureApi({ getToken: () => getToken() });

  const { data, isLoading, error } = useQuery({
    queryKey: ["me"],
    queryFn: () => api<Session>("/me"),
    enabled: !!isSignedIn,
    staleTime: 60_000,
  });

  if (error) return <div className="center">Accès impossible à votre organisation.</div>;
  if (isLoading || !data) return <div className="center">Chargement…</div>;

  const byKey = new Map(data.modules.map((m) => [m.key, m]));
  const value: Ctx = {
    session: data,
    hasModule: (k) => byKey.has(k),
    canWrite: (k) => !!byKey.get(k)?.can_write,
    switchOrg: (orgId) => {
      setActiveOrg(orgId);
      qc.clear(); // aucune donnée d'une organisation ne doit survivre au changement
      qc.invalidateQueries();
    },
  };
  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

/** Session fournie telle quelle (mode démo, tests) sans appel à /api/me. */
export function StaticSessionProvider({ session, children }: { session: Session; children: ReactNode }) {
  const byKey = new Map(session.modules.map((m) => [m.key, m]));
  const value: Ctx = {
    session,
    hasModule: (k) => byKey.has(k),
    canWrite: (k) => !!byKey.get(k)?.can_write,
    switchOrg: () => undefined,
  };
  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession() {
  const ctx = useContext(SessionContext);
  if (!ctx) throw new Error("useSession hors de SessionProvider");
  return ctx;
}

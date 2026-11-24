import { Suspense, type ReactNode } from "react";
import { Link, Outlet, useLocation } from "react-router-dom";
import { useSession } from "@/core/session/SessionProvider";
import { frontModules } from "@/core/modules/registry";
import { brandingVars, loadBrandFonts } from "./theme";

/**
 * Mise en page « focus » (branding.layout = "focus") : en-tête fixe avec la marque,
 * onglets horizontaux des modules métier, pas de barre latérale. Pensée pour les
 * organisations qui utilisent surtout un module (ex. une wedding planner).
 */
export function FocusShell({ userSlot }: { userSlot?: ReactNode }) {
  const { session, hasModule, switchOrg } = useSession();
  const b = session.branding;
  loadBrandFonts(b);
  const visible = frontModules.filter((m) => hasModule(m.key) && m.category !== "core");
  const name = b.app_name ?? session.org.name;
  const { pathname } = useLocation();
  const items = visible.flatMap((m) => m.nav);
  // Onglet actif : le préfixe le plus long qui correspond (/mariages/123 → Mariages, /mariages/reglages → Paramètres)
  const active = items.filter((n) => !n.soon && (pathname === n.to || pathname.startsWith(`${n.to}/`)))
    .sort((a, b) => b.to.length - a.to.length)[0]?.to;

  return (
    <div className="focus" style={brandingVars(b)}>
      <header className="focus-head">
        <div className="focus-top">
          <div>
            <div className="focus-mark">{b.logo_url ? <img src={b.logo_url} alt={name} /> : name}</div>
            <div className="focus-sub">Espace administrateur</div>
          </div>
          <div className="focus-tools">
            {visible.map((m) => m.headerTools && (
              <Suspense key={m.key} fallback={null}><m.headerTools /></Suspense>
            ))}
            {session.orgs.length > 1 && (
              <select value={session.org.id} onChange={(e) => switchOrg(e.target.value)} aria-label="Organisation">
                {session.orgs.map((o) => <option key={o.id} value={o.id}>{o.name}</option>)}
              </select>
            )}
            {userSlot}
          </div>
        </div>
        <nav className="focus-tabs" role="tablist">
          {items.map((n) =>
            n.soon ? (
              <button key={n.to} disabled title="Bientôt disponible">{n.label}</button>
            ) : (
              <Link key={n.to} to={n.to} className={active === n.to ? "active" : undefined}
                    aria-current={active === n.to ? "page" : undefined}>{n.label}</Link>
            ),
          )}
        </nav>
      </header>
      {session.subscription_status !== "active" && session.subscription_status !== "trialing" && (
        <p className="focus-warning">Abonnement inactif : accès en lecture seule.</p>
      )}
      <main className="focus-main"><Outlet /></main>
    </div>
  );
}

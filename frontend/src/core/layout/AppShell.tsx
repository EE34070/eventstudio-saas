import { NavLink, Outlet } from "react-router-dom";
import { UserButton } from "@clerk/react";
import { useSession } from "@/core/session/SessionProvider";
import { CATEGORY_LABELS, frontModules } from "@/core/modules/registry";

export function AppShell() {
  const { session, hasModule, switchOrg } = useSession();
  const visible = frontModules.filter((m) => hasModule(m.key));
  const categories = Object.keys(CATEGORY_LABELS) as (keyof typeof CATEGORY_LABELS)[];
  const appName = session.branding.app_name ?? "EventStudio";

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand">{session.branding.logo_url ? <img src={session.branding.logo_url} alt={appName} /> : appName}</div>

        {session.orgs.length > 1 && (
          <select value={session.org.id} onChange={(e) => switchOrg(e.target.value)} aria-label="Organisation">
            {session.orgs.map((o) => (
              <option key={o.id} value={o.id}>{o.name}</option>
            ))}
          </select>
        )}

        <nav>
          {categories.map((cat) => {
            const mods = visible.filter((m) => m.category === cat);
            if (!mods.length) return null;
            return (
              <section key={cat}>
                <h4>{CATEGORY_LABELS[cat]}</h4>
                {mods.flatMap((m) => m.nav).map((n) => (
                  <NavLink key={n.to} to={n.to}>{n.label}</NavLink>
                ))}
              </section>
            );
          })}
        </nav>

        {session.subscription_status !== "active" && session.subscription_status !== "trialing" && (
          <p className="warning">Abonnement inactif : accès en lecture seule.</p>
        )}
      </aside>

      <main>
        <header className="topbar">
          <span>{session.org.name}</span>
          <UserButton />
        </header>
        <Outlet />
      </main>
    </div>
  );
}

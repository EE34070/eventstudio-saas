import { Suspense, useCallback, useEffect, useState } from "react";
import { Link, NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { UserButton } from "@clerk/react";
import { LayoutGrid, Calendar, ClipboardList, Package, Truck, Menu, CircleHelp, Sun, Moon, Plus, Search, ChevronDown } from "lucide-react";
import { Sheet, SheetContent, SheetDescription, SheetTitle } from "@/components/ui/sheet";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Button } from "@/components/ui/button";
import { useMe } from "@/context/MeContext";
import { Loading } from "@/components/common";
import { GlobalSearch, Notifications } from "@/components/layout/TopbarTools";
import EventFormDialog from "@/components/events/EventFormDialog";
import { api } from "@/lib/api";
import { DASH, TOP, SECTIONS, GRID, PARAMS } from "@/components/layout/menu";

const TABS = [
  { to: "/dashboard", label: "Tableau", icon: LayoutGrid },
  { to: "/evenements", label: "Événements", icon: Calendar },
  { to: "/planning", label: "Planning", icon: ClipboardList },
  { to: "/catalogue", label: "Catalogue", icon: Package },
  { to: "/chargement", label: "Chargement", icon: Truck },
];

function PlanBanner({ plan }) {
  if (!plan || (!plan.read_only && plan.status !== "trialing")) return null;
  const end = plan.trial_ends_at ? new Date(plan.trial_ends_at).toLocaleDateString("fr-FR") : "";
  return (
    <div data-testid="plan-banner" className={`mb-4 rounded-xl px-4 py-2 text-sm ${plan.read_only ? "bg-red-50 text-red-800" : "bg-amber-50 text-amber-900"}`}>
      {plan.read_only ? "Abonnement inactif : votre espace est en lecture seule." : `Essai de l'offre ${plan.label} jusqu'au ${end}.`}
    </div>
  );
}

const Count = ({ n, red, testid }) => (n > 0 ? <span data-testid={testid} className={`ml-auto flex h-5 min-w-5 items-center justify-center rounded-full px-1.5 text-[10.5px] font-bold text-white ${red ? "bg-red-600" : "bg-primary"}`}>{n}</span> : null);

function isActive(item, loc) {
  const [path, qs] = item.to.split("?");
  if (!loc.pathname.startsWith(path)) return false;
  if (!qs) return true;
  const want = new URLSearchParams(qs).get("tab");
  return (new URLSearchParams(loc.search).get("tab") || "devis") === want;
}

function Item({ i, badges, onNavigate }) {
  const loc = useLocation();
  const on = isActive(i, loc);
  return (
    <Link to={i.to} onClick={onNavigate} data-testid={`nav-${i.key}`} aria-current={on ? "page" : undefined}
      className={`flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm transition-colors ${on ? "bg-secondary font-semibold text-foreground" : "text-muted-foreground hover:bg-secondary/60 hover:text-foreground"}`}>
      <i.icon className="h-[18px] w-[18px] shrink-0" /><span className="truncate">{i.label}</span>
      {i.badge && <Count n={badges?.[i.badge]} red={i.red} testid={`nav-badge-${i.key}`} />}
    </Link>
  );
}

function MenuList({ menu, onNavigate, toggle }) {
  const { can, modules, me } = useMe();
  const loc = useLocation();
  const hidden = menu?.hidden || (me?.user?.role === "technicien" ? SECTIONS[2].items.map((i) => i.key) : []);
  const ok = (i) => (!i.perm || i.perm.split("|").some(can)) && (!i.module || modules.includes(i.module)) && !hidden.includes(i.key) && (!me?.grid || !GRID[i.key] || !!me.grid[GRID[i.key]]?.view) && (!me?.plan || !GRID[i.key] || me.plan.sections.includes(GRID[i.key]));
  const collapsed = menu?.prefs?.collapsed_sections || [];
  const b = menu?.badges;
  return (
    <nav className="flex-1 overflow-y-auto scroll-thin px-3 pb-8" data-testid="main-menu">
      <button onClick={() => { onNavigate?.(); window.dispatchEvent(new Event("open-global-search")); }} data-testid="menu-search"
        className="mt-4 flex h-10 w-full items-center gap-2 rounded-full border border-border px-4 text-sm text-muted-foreground transition-colors hover:bg-secondary/60">
        <Search className="h-4 w-4" /><span className="flex-1 text-left">Rechercher…</span><kbd className="text-[11px]">⌘K</kbd>
      </button>
      <div className="mt-3 flex flex-wrap gap-1" data-testid="menu-top">
        {TOP.filter(ok).map((i) => (
          <Link key={i.key} to={i.to} onClick={onNavigate} title={i.label} aria-label={i.label} data-testid={`nav-${i.key}`}
            className={`icon-btn ${isActive(i, loc) ? "bg-secondary text-foreground" : "text-muted-foreground"}`}>
            <i.icon className="h-[18px] w-[18px]" />
            {i.badge && b?.[i.badge] > 0 && <span data-testid={`nav-badge-${i.key}`} className="absolute -right-0.5 -top-0.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-primary px-1 text-[10px] font-bold text-white">{b[i.badge]}</span>}
          </Link>
        ))}
      </div>
      <div className="mt-3"><Item i={DASH} badges={b} onNavigate={onNavigate} /></div>
      {SECTIONS.map((sec) => {
        const items = sec.items.filter(ok);
        if (!items.length) return null;
        const closed = collapsed.includes(sec.key);
        return (
          <div key={sec.key} className="mt-4" data-testid={`menu-section-${sec.key}`}>
            <button onClick={() => toggle(sec.key)} aria-expanded={!closed} data-testid={`menu-section-toggle-${sec.key}`} className="eyebrow mb-1 flex w-full items-center justify-between rounded-lg px-3 py-1.5 hover:bg-secondary/60">
              {sec.cat}<ChevronDown className={`h-3.5 w-3.5 transition-transform ${closed ? "-rotate-90" : ""}`} />
            </button>
            {!closed && items.map((i) => <Item key={i.key} i={i} badges={b} onNavigate={onNavigate} />)}
          </div>
        );
      })}
      {ok(PARAMS) && <div className="mt-4 border-t border-border pt-3"><Item i={PARAMS} badges={b} onNavigate={onNavigate} /></div>}
    </nav>
  );
}

const Brand = ({ org }) => (
  <Link to="/dashboard" className="flex min-w-0 items-center gap-2.5" data-testid="brand-link">
    <span className="brand-mark">{(org?.name || "E")[0]}</span>
    <span className="font-brand truncate text-lg" data-testid="org-name">{org?.name}</span>
  </Link>
);

function BottomNav() {
  return (
    <nav className="shadow-soft fixed inset-x-3 bottom-3 z-40 mx-auto flex max-w-3xl rounded-3xl border border-border bg-card px-1.5 py-2 lg:hidden" data-testid="bottom-nav">
      {TABS.map((t) => (
        <NavLink key={t.to} to={t.to} data-testid={`tab-nav-${t.to.slice(1)}`}
          className={({ isActive }) => `flex min-w-0 flex-1 flex-col items-center gap-1 rounded-2xl py-1.5 text-[12px] transition-colors ${isActive ? "font-semibold text-foreground" : "text-[#737373] hover:text-foreground"}`}>
          {({ isActive }) => <><t.icon className={`h-5 w-5 ${isActive ? "text-primary" : ""}`} /><span className="max-w-full truncate">{t.label}</span></>}
        </NavLink>
      ))}
    </nav>
  );
}

function Sidebar({ org, me, menu, toggle, onNavigate }) {
  return (
    <>
      <div className="px-6 pt-6"><Brand org={org} /></div>
      <MenuList menu={menu} toggle={toggle} onNavigate={onNavigate} />
      <div className="border-t border-border px-6 py-4">
        <div className="truncate text-sm font-semibold" data-testid="current-user-name">{me?.user?.name}</div>
        <div className="text-xs text-muted-foreground" data-testid="current-user-role">{me?.roles?.find((r) => r.id === me?.user?.role)?.label}</div>
      </div>
    </>
  );
}

export default function AppShell() {
  const { org, me, can } = useMe();
  const [open, setOpen] = useState(false);
  const [menu, setMenu] = useState(null);
  const [newEvent, setNewEvent] = useState(false);
  const [dark, setDark] = useState(() => localStorage.getItem("theme") === "dark");
  const loc = useLocation();
  const nav = useNavigate();
  const desktop = () => window.matchMedia("(min-width: 1024px)").matches;
  useEffect(() => { const h = (e) => { if ((e.ctrlKey || e.metaKey) && e.shiftKey && e.key.toLowerCase() === "v") { e.preventDefault(); nav("/demande/nouvelle"); } }; window.addEventListener("keydown", h); return () => window.removeEventListener("keydown", h); }, [nav]);
  useEffect(() => { document.documentElement.classList.toggle("dark", dark); localStorage.setItem("theme", dark ? "dark" : "light"); }, [dark]);
  useEffect(() => { window.scrollTo(0, 0); api.get("/menu").then((r) => setMenu(r.data)).catch(() => {}); }, [loc.pathname]);
  const toggle = useCallback((key) => setMenu((m) => {
    const cur = m?.prefs?.collapsed_sections || [];
    const collapsed_sections = cur.includes(key) ? cur.filter((k) => k !== key) : [...cur, key];
    api.put("/menu/prefs", { collapsed_sections }).catch(() => {});
    return { ...(m || {}), prefs: { ...(m?.prefs || {}), collapsed_sections } };
  }), []);

  return (
    <div className="min-h-screen bg-background lg:pl-[272px]">
      <aside className="fixed inset-y-0 left-0 z-30 hidden w-[272px] flex-col border-r border-border bg-background lg:flex" data-testid="sidebar">
        {!open && <Sidebar org={org} me={me} menu={menu} toggle={toggle} />}
      </aside>
      <Sheet open={open} onOpenChange={setOpen}>
        <SheetContent side="left" className="flex w-[290px] flex-col p-0" data-testid="mobile-menu">
          <SheetTitle className="sr-only">Menu</SheetTitle>
          <SheetDescription className="sr-only">Navigation principale</SheetDescription>
          {open && <Sidebar org={org} me={me} menu={menu} toggle={toggle} onNavigate={() => setOpen(false)} />}
        </SheetContent>
      </Sheet>
      {me?.preview && <div className="sticky top-0 z-40 flex flex-wrap items-center justify-center gap-3 bg-amber-400 px-4 py-2 text-sm font-semibold text-black" data-testid="member-preview-banner">Aperçu admin : vous voyez l'application comme {me.preview} (lecture seule)<button className="rounded-full bg-black px-3 py-1 text-xs text-white" onClick={() => { sessionStorage.removeItem("view-as-member"); window.location.href = "/acces"; }} data-testid="member-preview-exit">Quitter l'aperçu</button></div>}
      <header className="mx-auto flex h-16 w-full max-w-[1400px] items-center gap-2 px-3 sm:px-8" data-testid="app-header">
        <button className="icon-btn lg:hidden" onClick={() => !desktop() && setOpen(true)} data-testid="menu-button" aria-label="Menu"><Menu className="h-5 w-5" /></button>
        <div className="min-w-0 lg:hidden"><Brand org={org} /></div>
        <div className="ml-auto flex shrink-0 items-center gap-0.5 sm:gap-1.5">
          <GlobalSearch />
          <Popover>
            <PopoverTrigger asChild><button className="icon-btn hidden sm:inline-flex" data-testid="help-button" aria-label="Aide"><CircleHelp className="h-5 w-5" /></button></PopoverTrigger>
            <PopoverContent align="end" className="w-72 text-sm" data-testid="help-panel">
              <div className="font-semibold">Aide rapide</div>
              <ul className="mt-2 space-y-1.5 text-muted-foreground">
                <li><b className="text-foreground">Ctrl K / ⌘K</b> : recherche globale</li>
                <li>Les sections du menu se replient ; votre choix est mémorisé</li>
                <li>Le chargement du jour est généré chaque matin à 6 h</li>
              </ul>
            </PopoverContent>
          </Popover>
          <button className="icon-btn" onClick={() => setDark(!dark)} data-testid="theme-toggle" aria-label="Basculer clair/sombre">{dark ? <Moon className="h-5 w-5" /> : <Sun className="h-5 w-5" />}</button>
          <Notifications />
          {can("finance:read") && can("events:write") && <Button variant="outline" className="ml-1 hidden px-4 lg:inline-flex" onClick={() => nav("/devis-factures?new=1")} data-testid="topbar-new-quote"><Plus />Devis</Button>}
          {can("events:write") && (
            <Button className="ml-1 px-3 sm:px-5" onClick={() => setNewEvent(true)} data-testid="new-event-button"><Plus /><span className="hidden md:inline">Nouvel Événement</span></Button>
          )}
          <div className="ml-1.5 flex items-center"><UserButton /></div>
        </div>
      </header>
      <main className="mx-auto w-full max-w-[1400px] px-4 pb-36 pt-6 sm:px-8 sm:pt-10">
        {can("events:write") && <button onClick={() => nav("/demande/nouvelle")} data-testid="fab-paste-request" className="fixed bottom-24 right-4 z-40 inline-flex h-12 items-center gap-2 rounded-full bg-orange-500 px-5 text-sm font-semibold text-white shadow-lg transition-transform hover:scale-105 lg:bottom-6"><Plus className="h-4 w-4" />Coller une demande</button>}
        <PlanBanner plan={me?.plan} />
        <Suspense fallback={<Loading />}><Outlet /></Suspense>
      </main>
      <BottomNav />
      <EventFormDialog open={newEvent} onOpenChange={setNewEvent} onSaved={(r) => nav(`/evenements/${r.id}`)} />
    </div>
  );
}

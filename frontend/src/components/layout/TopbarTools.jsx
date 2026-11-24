import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Search, Bell, AlertTriangle, Wrench, UserX, CalendarCheck2, Users, MapPin, Boxes, FileText, Receipt } from "lucide-react";
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { api } from "@/lib/api";

const GROUPS = [
  { key: "events", label: "Événements", icon: CalendarCheck2, to: (r) => `/evenements/${r.id}` },
  { key: "contacts", label: "Contacts", icon: Users, to: (r) => `/contacts?id=${r.id}` },
  { key: "venues", label: "Lieux", icon: MapPin, to: (r) => `/lieux?id=${r.id}` },
  { key: "equipment", label: "Matériel", icon: Boxes, to: (r) => `/catalogue?q=${encodeURIComponent(r.sub)}` },
  { key: "quotes", label: "Devis", icon: FileText, to: (r) => (r.event_id ? `/evenements/${r.event_id}` : "/devis-factures?tab=devis") },
  { key: "invoices", label: "Factures", icon: Receipt, to: (r) => (r.event_id ? `/evenements/${r.event_id}` : "/devis-factures?tab=factures") },
];

export function GlobalSearch() {
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const [res, setRes] = useState(null);
  const nav = useNavigate();

  useEffect(() => {
    const onKey = (e) => { if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") { e.preventDefault(); setOpen(true); } };
    const onOpen = () => setOpen(true);
    window.addEventListener("keydown", onKey);
    window.addEventListener("open-global-search", onOpen);
    return () => { window.removeEventListener("keydown", onKey); window.removeEventListener("open-global-search", onOpen); };
  }, []);

  useEffect(() => {
    if (q.trim().length < 2) { setRes(null); return; }
    const t = setTimeout(() => { api.get("/search", { params: { q } }).then((r) => setRes(r.data)).catch(() => setRes(null)); }, 220);
    return () => clearTimeout(t);
  }, [q]);

  const go = (to) => { setOpen(false); setQ(""); nav(to); };
  const total = res ? GROUPS.reduce((n, g) => n + (res[g.key]?.length || 0), 0) : 0;

  return (
    <>
      <button data-testid="global-search-button" onClick={() => setOpen(true)} className="icon-btn" title="Rechercher (Ctrl K)" aria-label="Rechercher"><Search className="h-5 w-5" /></button>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="max-w-xl gap-0 overflow-hidden p-0">
          <DialogTitle className="sr-only">Recherche globale</DialogTitle>
          <div className="flex items-center gap-2 border-b border-border px-4">
            <Search className="h-4 w-4 text-muted-foreground" />
            <input data-testid="global-search-input" autoFocus value={q} onChange={(e) => setQ(e.target.value)} placeholder="Tapez au moins 2 caractères…" className="h-12 flex-1 bg-transparent text-sm outline-none" />
          </div>
          <div className="max-h-[60vh] overflow-y-auto p-2" data-testid="global-search-results">
            {res && total === 0 && <div className="p-6 text-center text-sm text-muted-foreground">Aucun résultat</div>}
            {res && GROUPS.map((g) => res[g.key]?.length ? (
              <div key={g.key} className="mb-2">
                <div className="eyebrow px-2 py-1.5">{g.label}</div>
                {res[g.key].map((r) => (
                  <button key={r.id} onClick={() => go(g.to(r))} data-testid={`search-result-${g.key}-${r.id}`} className="flex w-full items-center gap-3 rounded-lg px-2 py-2 text-left hover:bg-secondary">
                    <g.icon className="h-4 w-4 text-primary" />
                    <span className="flex-1 truncate text-sm">{r.label}</span>
                    <span className="text-xs text-muted-foreground">{r.sub}</span>
                  </button>
                ))}
              </div>
            ) : null)}
          </div>
        </DialogContent>
      </Dialog>
    </>
  );
}

const ICONS = { conflit: AlertTriangle, maintenance: Wrench, technicien: UserX };

export function Notifications() {
  const [data, setData] = useState(null);
  const nav = useNavigate();
  const load = () => api.get("/notifications").then((r) => setData(r.data)).catch(() => {});
  useEffect(() => { load(); }, []);
  const count = data?.alerts?.length || 0;
  return (
    <Popover onOpenChange={(o) => { if (o) load(); }}>
      <PopoverTrigger asChild>
        <button data-testid="notifications-button" className="icon-btn" aria-label="Notifications">
          <Bell className="h-5 w-5" />
          {count > 0 && <span data-testid="notifications-count" className="absolute -right-0.5 -top-0.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-primary px-1 text-[10px] font-bold text-white">{count}</span>}
        </button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-[380px] p-0" data-testid="notifications-panel">
        <div className="border-b border-border px-4 py-3 text-sm font-semibold">Notifications</div>
        <div className="max-h-[420px] overflow-y-auto">
          {data?.alerts?.map((a, i) => {
            const I = ICONS[a.type] || AlertTriangle;
            return (
              <button key={i} onClick={() => a.event_id ? nav(`/evenements/${a.event_id}`) : nav("/catalogue?tab=maintenance")} className="flex w-full gap-3 border-b border-border px-4 py-3 text-left hover:bg-secondary/60">
                <I className={`mt-0.5 h-4 w-4 shrink-0 ${a.severity === "danger" ? "text-destructive" : "text-amber-600"}`} />
                <div><div className="text-[13px] font-medium">{a.title}</div><div className="text-xs text-muted-foreground">{a.detail}</div></div>
              </button>
            );
          })}
          <div className="eyebrow px-4 pt-3">Activité récente</div>
          {data?.activity?.map((h, i) => (
            <button key={i} onClick={() => nav(`/evenements/${h.event_id}`)} className="block w-full px-4 py-2 text-left hover:bg-secondary/60">
              <div className="text-[13px]"><span className="font-medium">{h.action}</span> · {h.title}</div>
              <div className="text-xs text-muted-foreground">{h.detail} — {h.by}</div>
            </button>
          ))}
          {!data && <div className="p-4 text-sm text-muted-foreground">Chargement…</div>}
        </div>
      </PopoverContent>
    </Popover>
  );
}

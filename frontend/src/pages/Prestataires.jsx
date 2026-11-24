import { useCallback, useEffect, useState } from "react";
import { TrashBtn, Pick, BulkDelete } from "@/components/Trash";
import { Link, useSearchParams } from "react-router-dom";
import { toast } from "sonner";
import { Download, Handshake, Plus, Tags, Upload } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { PageHeader, Loading, EmptyState, SearchPill } from "@/components/common";
import { api, downloadPdf, errMsg } from "@/lib/api";
import { fmtDate, fmtEur2 } from "@/lib/constants";
import { Badge, M_STATUS, P_STATUS, R_STATUS, priceLabel, travelLabel } from "@/components/providers/shared";
import { ProviderDialog } from "@/components/providers/ProviderDialog";
import { ProviderSheet } from "@/components/providers/ProviderSheet";
import { ImportDialog, CategoriesDialog, TemplatesDialog } from "@/components/providers/ProviderTools";
import { PlannerRanking } from "@/components/providers/PlannerEvents";
import { RequestDialog } from "@/components/providers/RequestDialog";

const TABS = [["liste", "Prestataires"], ["demandes", "Demandes"], ["missions", "Missions"], ["planners", "Organisateurs"]];
const norm = (s) => String(s || "").normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase();
const th = "px-4 py-3 text-left text-xs font-semibold text-muted-foreground";
const td = "px-4 py-3 align-top";

export default function Prestataires() {
  const [params, setParams] = useSearchParams();
  const tab = params.get("tab") || "liste";
  const [cats, setCats] = useState([]);
  const [rows, setRows] = useState(null);
  const [reqs, setReqs] = useState(null);
  const [missions, setMissions] = useState(null);
  const [q, setQ] = useState("");
  const [cat, setCat] = useState("all");
  const [dialog, setDialog] = useState(null);
  const [edit, setEdit] = useState(null);
  const [version, setVersion] = useState(0);
  const openId = params.get("id");
  const eventId = params.get("event");
  const set = (k, v) => { v ? params.set(k, v) : params.delete(k); setParams(params); };
  const [pick, setPick] = useState([]);
  const load = useCallback(() => {
    api.get("/provider-categories").then((r) => setCats(r.data)).catch((e) => toast.error(errMsg(e)));
    api.get("/providers").then((r) => setRows(r.data)).catch(() => {});
    api.get("/service-requests").then((r) => setReqs(r.data)).catch(() => {});
    api.get("/missions").then((r) => setMissions(r.data)).catch(() => {});
    setVersion((v) => v + 1);
  }, []);
  useEffect(() => { load(); }, [load]);
  useEffect(() => { if (eventId) setDialog("request"); }, [eventId]);
  const lab = Object.fromEntries(cats.map((c) => [c.key, c.label]));
  const n = norm(q);
  const shown = (rows || []).filter((r) => (cat === "all" || r.categories.includes(cat))
    && (!n || norm([r.display_name, r.contact_name, r.company, r.base_city, r.email, ...r.tags, ...r.categories.map((c) => lab[c])].join(" ")).includes(n)));
  const patchMission = async (id, body) => { try { await api.patch(`/missions/${id}`, body); load(); } catch (e) { toast.error(errMsg(e)); } };

  return (
    <div data-testid="providers-page">
      <PageHeader title="Prestataires" subtitle="Trouvez le bon prestataire, envoyez la demande et confirmez-le en quelques clics."
        actions={<>
          <Button variant="outline" size="sm" onClick={() => setDialog("categories")} data-testid="providers-categories-button"><Tags />Métiers</Button>
          <Button variant="outline" size="sm" onClick={() => setDialog("templates")} data-testid="providers-templates-button">Modèles</Button>
          <Button variant="outline" size="sm" onClick={() => setDialog("import")} data-testid="providers-import-button"><Upload />Importer</Button>
          <Button variant="outline" size="sm" onClick={() => downloadPdf("/providers/export", "prestataires.csv").catch((e) => toast.error(errMsg(e)))} data-testid="providers-export-button"><Download />Exporter</Button>
          <Button variant="outline" size="sm" onClick={() => { setEdit(null); setDialog("provider"); }} data-testid="new-provider-button"><Plus />Nouveau prestataire</Button>
          <Button size="sm" onClick={() => setDialog("request")} data-testid="new-request-button"><Handshake />Trouver un prestataire</Button>
        </>} />
      <div className="mb-5 flex flex-wrap gap-1.5">
        {TABS.map(([k, l]) => <button key={k} onClick={() => set("tab", k === "liste" ? "" : k)} data-testid={`providers-tab-${k}`}
          className={`h-9 rounded-full border px-4 text-sm font-medium ${tab === k ? "border-primary bg-primary text-white" : "border-border hover:bg-secondary"}`}>{l}{k === "missions" && missions?.some((m) => m.to_rate) ? ` (${missions.filter((m) => m.to_rate).length} à noter)` : ""}</button>)}
      </div>

      {tab === "liste" && (!rows ? <Loading /> : (<>
        <div className="mb-4 flex flex-wrap items-center gap-3">
          <SearchPill value={q} onChange={setQ} placeholder="Nom, métier, ville, tag…" testid="providers-search-input" className="md:w-96" />
          <Select value={cat} onValueChange={setCat}><SelectTrigger className="w-56" data-testid="providers-category-filter"><SelectValue /></SelectTrigger>
            <SelectContent><SelectItem value="all">Tous les métiers</SelectItem>{cats.map((c) => <SelectItem key={c.key} value={c.key}>{c.label}</SelectItem>)}</SelectContent></Select>
          <span className="text-sm text-muted-foreground" data-testid="providers-count">{shown.length} prestataire(s)</span>
        </div>
        {!shown.length ? <EmptyState icon={Handshake} title="Aucun prestataire" text="Créez une fiche ou importez votre fichier CSV / Excel." /> : (
          <div className="card-soft overflow-x-auto"><div className="p-2 empty:hidden"><BulkDelete kind="provider" picked={pick} onDone={() => { setPick([]); load(); }} /></div><table className="w-full min-w-[900px] text-sm" data-testid="providers-table">
            <thead><tr className="border-b border-border"><th className={th}>Prestataire</th><th className={th}>Métiers</th><th className={th}>Zone</th><th className={th}>Prix</th><th className={th}>Déplacement</th><th className={th}>Note</th><th className={th}>Réponses</th><th className={th}>Statut</th><th className={th} /></tr></thead>
            <tbody>{shown.map((r) => (
              <tr key={r.id} className="cursor-pointer border-b border-border last:border-b-0 hover:bg-secondary/50" onClick={() => set("id", r.id)} data-testid={`provider-row-${r.id}`}>
                <td className={td}><div className="font-semibold"><Pick id={r.id} pick={pick} setPick={setPick} />{r.display_name}</div><div className="text-xs text-muted-foreground">{r.email || "E-mail manquant"}</div></td>
                <td className={td}>{r.categories.map((c) => lab[c] || c).join(", ")}{r.tags.length > 0 && <div className="text-xs text-muted-foreground">{r.tags.join(", ")}</div>}</td>
                <td className={td}>{r.base_city || "—"}{r.radius_km ? ` + ${r.radius_km} km` : ""}{r.departments.length > 0 && <div className="text-xs text-muted-foreground">dép. {r.departments.join(", ")}</div>}</td>
                <td className={td}>{fmtEur2(r.base_rate)} {r.vat_mode === "subject" ? "HT" : "net"}<div className="text-xs text-muted-foreground">{r.vat_mode === "subject" ? `${fmtEur2(r.base_rate * (1 + r.vat_rate / 100))} TTC` : "TVA non applicable"} · {r.included_hours} h</div></td>
                <td className={td}>{travelLabel(r)}</td>
                <td className={td}>{r.rating ? `${r.rating} / 5` : "—"}</td>
                <td className={td}>{r.response_rate == null ? "—" : `${r.response_rate} %`}</td>
                <td className={td}><Badge tone={{ active: "ok", test: "warn", blocked: "bad" }[r.status]}>{P_STATUS[r.status]}</Badge>{r.urssaf_alert && <div className="mt-1"><Badge tone={r.urssaf_alert === "expired" ? "bad" : "warn"} testid="provider-urssaf-alert">URSSAF {r.urssaf_alert === "expired" ? "expirée" : "à renouveler"}</Badge></div>}</td><td className={td}><TrashBtn kind="provider" id={r.id} name={r.display_name} onDone={load} /></td>
              </tr>))}</tbody></table></div>)}
      </>))}

      {tab === "demandes" && (!reqs ? <Loading /> : !reqs.length ? <EmptyState icon={Handshake} title="Aucune demande" text="Décrivez un besoin pour trouver les prestataires qui correspondent." /> : (
        <div className="card-soft divide-y divide-border" data-testid="requests-list">{reqs.map((r) => (
          <Link key={r.id} to={`/prestataires/demandes/${r.id}`} className="flex flex-wrap items-center gap-3 px-5 py-4 hover:bg-secondary/50" data-testid={`request-row-${r.id}`}>
            <div className="min-w-0 flex-1"><div className="font-semibold">{r.category_label}{r.quantity > 1 ? ` × ${r.quantity}` : ""} — {fmtDate(r.date)}, {r.start_time}–{r.end_time}</div><div className="text-sm text-muted-foreground">{r.venue_city || r.venue_address}</div></div>
            <span className="text-sm text-muted-foreground">{r.recipients} envoi(s) · {r.replied} réponse(s) · {r.available} disponible(s)</span>
            <Badge tone={{ filled: "ok", cancelled: "bad", draft: "muted" }[r.status] || "info"}>{R_STATUS[r.status]}</Badge>
          </Link>))}</div>))}

      {tab === "missions" && (!missions ? <Loading /> : !missions.length ? <EmptyState icon={Handshake} title="Aucune mission" text="Une mission est créée quand vous retenez un prestataire." /> : (
        <div className="card-soft divide-y divide-border" data-testid="missions-list">{missions.map((m) => (
          <div key={m.id} className="flex flex-wrap items-center gap-3 px-5 py-4" data-testid={`mission-row-${m.id}`}>
            <Link to={`/prestataires/demandes/${m.request_id}`} className="min-w-0 flex-1 hover:underline"><div className="font-semibold">{m.provider_name} — {m.category_label}</div>
              <div className="text-sm text-muted-foreground">{fmtDate(m.date)}, {m.start_time}–{m.end_time} · {m.venue_city} · {priceLabel(m.vat_mode, m.total_ht, m.total_ttc)}</div></Link>
            {m.missing_equipment.length > 0 && <Badge tone="warn">Matériel à prévoir</Badge>}
            {m.to_rate && <Badge tone="info" testid="mission-to-rate">À noter</Badge>}
            <Select value={String(m.rating || "")} onValueChange={(v) => patchMission(m.id, { rating: Number(v) })}><SelectTrigger className="h-8 w-28 text-xs" data-testid={`mission-rating-${m.id}`}><SelectValue placeholder="Noter" /></SelectTrigger>
              <SelectContent>{[1, 2, 3, 4, 5].map((x) => <SelectItem key={x} value={String(x)}>{x} / 5</SelectItem>)}</SelectContent></Select>
            <Select value={m.status} onValueChange={(v) => patchMission(m.id, { status: v })}><SelectTrigger className="h-8 w-36 text-xs" data-testid={`mission-status-${m.id}`}><SelectValue /></SelectTrigger>
              <SelectContent>{Object.entries(M_STATUS).map(([k, l]) => <SelectItem key={k} value={k}>{l}</SelectItem>)}</SelectContent></Select>
          </div>))}</div>))}

      {tab === "planners" && <PlannerRanking categories={cats} onOpen={(id) => set("id", id)} />}

      <ProviderDialog open={dialog === "provider"} onOpenChange={(o) => setDialog(o ? "provider" : null)} provider={edit} categories={cats} onSaved={load} onOpenExisting={(id) => set("id", id)} />
      <ProviderSheet id={openId} initialTab={params.get("ptab")} onClose={() => { params.delete("ptab"); set("id", ""); }} categories={cats} version={version} onEdit={(p) => { setEdit(p); setDialog("provider"); }} />
      <TemplatesDialog open={dialog === "templates"} onOpenChange={(o) => setDialog(o ? "templates" : null)} />
      <ImportDialog open={dialog === "import"} onOpenChange={(o) => setDialog(o ? "import" : null)} onDone={load} />
      <CategoriesDialog open={dialog === "categories"} onOpenChange={(o) => setDialog(o ? "categories" : null)} categories={cats} onChanged={load} />
      <RequestDialog open={dialog === "request"} onOpenChange={(o) => { setDialog(o ? "request" : null); if (!o && eventId) set("event", ""); }} categories={cats} eventId={eventId} />
    </div>
  );
}

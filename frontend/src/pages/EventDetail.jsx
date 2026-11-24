import { useCallback, useEffect, useState } from "react";
import { EventComm } from "@/components/communication/EventComm";
import { Link, useNavigate, useParams } from "react-router-dom";
import { toast } from "sonner";
import { ArrowLeft, AlertTriangle, CalendarDays, MapPin, User, Pencil, Trash2, Users } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle } from "@/components/ui/alert-dialog";
import { Loading, StatusBadge } from "@/components/common";
import EventFormDialog from "@/components/events/EventFormDialog";
import { InfosTab, PrestationsTab } from "@/components/events/TabsInfoPrestations";
import MaterielTab from "@/components/events/TabMateriel";
import PortalTab from "@/components/events/PortalTab";
import DevisTab from "@/components/events/TabDevis";
import { TabDeroule } from "@/components/events/TabDeroule";
import { DjBadge, DjBanner } from "@/components/dj/DjPlanning";
import DjBlock from "@/components/events/DjBlock";
import { TabDj } from "@/components/events/TabDj";
import { EventMusic } from "@/pages/Musique";
import { StaffTab } from "@/pages/StaffAdmin";
import { EquipeTab, PlanningTab, DocumentsTab, FinancesTab, HistoryTab } from "@/components/events/TabsOther";
import { api, errMsg, conflictsOf } from "@/lib/api";
import { STATUSES, fmtDT, fmtEur } from "@/lib/constants";
import { useMe } from "@/context/MeContext";

export const showError = (err) => {
  const c = conflictsOf(err);
  toast.error(errMsg(err), c ? { description: c.map((x) => `${x.ref} ${x.name} : demandé ${x.requested}, dispo ${x.available}`).join(" · "), duration: 8000 } : undefined);
};

function Stepper({ status }) {
  const idx = STATUSES.findIndex((s) => s.id === status);
  return (
    <div className="mt-6 flex gap-1.5 overflow-x-auto scroll-thin" data-testid="status-stepper">
      {STATUSES.map((s, i) => (
        <div key={s.id} className="min-w-[96px] flex-1">
          <div className={`h-1.5 rounded-full ${i <= idx ? "bg-primary" : "bg-border"}`} />
          <div className={`mt-1.5 text-[11px] ${i === idx ? "font-semibold text-foreground" : "text-muted-foreground"}`}>{s.label}</div>
        </div>
      ))}
    </div>
  );
}

function ConflictBanner({ conflicts }) {
  if (!conflicts?.length) return null;
  return (
    <div className="mt-6 rounded-xl border border-red-500/30 bg-red-500/10 p-4" data-testid="conflict-banner">
      <div className="flex items-center gap-2 text-sm font-semibold text-red-600 dark:text-red-400"><AlertTriangle className="h-4 w-4" />Conflit de matériel sur la période</div>
      <ul className="mt-2 space-y-1 text-xs text-foreground">
        {conflicts.map((c) => (
          <li key={c.equipment_id}><b>{c.ref} {c.name}</b> : demandé {c.requested}, disponible {c.available} (manque {c.missing})
            {c.events.length > 0 && <> — déjà réservé par {c.events.map((e) => <Link key={e.id} className="underline" to={`/evenements/${e.id}`}>{e.code}</Link>).reduce((a, b) => [a, ", ", b])}</>}
          </li>
        ))}
      </ul>
      <div className="mt-2 text-xs text-red-600 dark:text-red-400">La confirmation reste possible : les manques sont listés dans le bloc « Manques » de l'onglet Matériel.</div>
    </div>
  );
}

export default function EventDetail() {
  const { id } = useParams();
  const nav = useNavigate();
  const { can } = useMe();
  const [ev, setEv] = useState(null);
  const [edit, setEdit] = useState(false);
  const [del, setDel] = useState(false);
  const [tab, setTab] = useState(new URLSearchParams(window.location.search).get("tab") || "infos");

  const load = useCallback(() => api.get(`/events/${id}`).then((r) => setEv(r.data)).catch(() => { toast.error("Événement introuvable"); nav("/evenements"); }), [id, nav]);
  useEffect(() => { load(); }, [load]);
  const [quotes, setQuotes] = useState(null);
  const loadQuotes = useCallback(() => api.get(`/events/${id}/quotes`).then((r) => setQuotes(r.data)).catch(() => setQuotes([])), [id]);
  useEffect(() => { loadQuotes(); }, [loadQuotes]);

  const save = async (patch, msg = "Modifications enregistrées") => {
    try {
      const r = await api.patch(`/events/${id}`, patch);
      setEv(r.data);
      toast.success(msg);
      (r.data.dj_conflicts || []).forEach((c) => toast.error(`Conflit DJ : ${c}`, { duration: 12000 }));
      return true;
    } catch (err) {
      showError(err);
      return false;
    }
  };
  const [shortAsk, setShortAsk] = useState(null);
  const setStatus = async (status) => {
    if (status === "confirme" && ["demande", "devis_envoye"].includes(ev.status)) {
      try { const p = (await api.get(`/events/${id}/shortages/preview`)).data; if (p.lines.length) { setShortAsk(p); return; } } catch { /* confirmation sans aperçu */ }
    }
    return doStatus(status);
  };
  const doStatus = async (status) => {
    try {
      const r = await api.post(`/events/${id}/status`, { status });
      setEv(r.data);
      toast.success("Statut mis à jour");
    } catch (err) {
      showError(err);
    }
  };
  const remove = async () => {
    try { await api.delete(`/events/${id}`); toast.success("Événement supprimé"); nav("/evenements"); } catch (err) { showError(err); }
  };

  if (!ev) return <Loading />;
  const canStatus = can("events:write") || can("finance:write");
  const props = { ev, save, setStatus, reload: load };
  return (
    <div>
      <Link to="/evenements" className="mb-5 inline-flex items-center gap-1.5 text-xs font-medium text-muted-foreground hover:text-foreground" data-testid="back-to-events"><ArrowLeft className="h-3.5 w-3.5" />Événements</Link>
      <div className="card-soft p-6 sm:p-8 fade-up">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-3"><span className="font-mono text-xs text-muted-foreground" data-testid="event-code">{ev.code}</span><StatusBadge status={ev.status} testid="event-status-badge" />{ev.shortages_count > 0 && <button onClick={() => setTab("materiel")} className="rounded-full bg-red-600 px-2.5 py-0.5 text-xs font-semibold text-white" data-testid="event-shortages-badge">{ev.shortages_count} manque{ev.shortages_count > 1 ? "s" : ""} à traiter</button>}<span className="text-xs text-muted-foreground">{ev.type}</span></div>
            <h1 className="mt-2 font-display text-3xl sm:text-4xl" data-testid="event-title">{ev.title}</h1>
            <div className="mt-3 flex flex-wrap gap-x-5 gap-y-1.5 text-sm text-muted-foreground">
              <span className="flex items-center gap-1.5"><CalendarDays className="h-4 w-4" />{ev.date_tbc ? "Date à confirmer" : <>{fmtDT(ev.start)} → {fmtDT(ev.end)}</>}</span>
              <span className="flex items-center gap-1.5"><MapPin className="h-4 w-4" />{ev.venue ? `${ev.venue.name}, ${ev.venue.city}` : "Lieu à définir"}</span>
              {ev.client && <span className="flex items-center gap-1.5"><User className="h-4 w-4" />{ev.client.display_name}</span>}
              <span className="flex items-center gap-1.5"><Users className="h-4 w-4" />{ev.chef_projet_name || "Chef de projet à définir"}</span>
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <DjBadge eid={ev.id} onOpen={() => setTab(can("providers:manage") ? "dj" : "devis")} />
            {ev.amount_ht != null && <div className="mr-3 text-right"><div className="eyebrow">Total HT</div><div className="font-display text-2xl" data-testid="event-amount-ht">{fmtEur(ev.amount_ht)}</div></div>}
            {canStatus && (
              <Select value={ev.status} onValueChange={setStatus}>
                <SelectTrigger className="w-44" data-testid="event-status-select"><SelectValue /></SelectTrigger>
                <SelectContent>{STATUSES.map((s) => <SelectItem key={s.id} value={s.id} data-testid={`status-option-${s.id}`}>{s.label}</SelectItem>)}</SelectContent>
              </Select>
            )}
            {can("providers:manage") && <Button variant="outline" onClick={() => nav(`/prestataires?tab=demandes&event=${ev.id}`)} data-testid="find-provider-button">Trouver un prestataire</Button>}
            {can("events:write") && <Button variant="outline" onClick={() => setEdit(true)} data-testid="edit-event-button"><Pencil className="mr-1.5 h-4 w-4" />Modifier</Button>}
            {can("events:delete") && <Button variant="ghost" size="icon" onClick={() => setDel(true)} data-testid="delete-event-button"><Trash2 className="h-4 w-4" /></Button>}
          </div>
        </div>
        <Stepper status={ev.status} />
        <ConflictBanner conflicts={ev.conflicts} />
      </div>
      <Tabs value={tab} onValueChange={setTab} className="mt-6">
        <TabsList className="h-auto flex-wrap justify-start bg-transparent p-0 gap-1" data-testid="event-tabs">
          {[["infos", "Infos"], ["prestations", "Prestations"], ["materiel", "Matériel"], ["devis", `Devis (${quotes?.length ?? 0})`], ...(can("providers:manage") ? [["dj", "DJ"]] : []), ["equipe", "Équipe"], ["planning", "Planning"], ["deroule", "Déroulé"], ["documents", "Documents"], ["portail", "Espace client"], ["musique", "Musique"], ...(can("comms:view") ? [["communication", "Communication"]] : []), ...(can("providers:manage") ? [["staff", "Staff"]] : []), ["finances", "Finances"], ["historique", "Historique"]]
            .filter(([k]) => k !== "finances" || can("finance:read"))
            .map(([k, l]) => <TabsTrigger key={k} value={k} data-testid={`tab-${k}`} className="rounded-lg border border-transparent px-3.5 py-2 data-[state=active]:border-border data-[state=active]:bg-card data-[state=active]:shadow-sm">{l}</TabsTrigger>)}
        </TabsList>
        <div className="mt-4">
          <TabsContent value="infos"><InfosTab {...props} /></TabsContent>
          <TabsContent value="prestations"><PrestationsTab {...props} /></TabsContent>
          <TabsContent value="materiel"><MaterielTab {...props} /></TabsContent>
          <TabsContent value="devis"><DjBanner eid={ev.id} /><DevisTab ev={ev} quotes={quotes} reloadQuotes={loadQuotes} reload={load} /><DjBlock eid={ev.id} /></TabsContent>
          {can("providers:manage") && <TabsContent value="dj"><TabDj ev={ev} /><DjBlock eid={ev.id} /></TabsContent>}
          <TabsContent value="equipe"><EquipeTab {...props} /></TabsContent>
          <TabsContent value="planning"><PlanningTab {...props} /></TabsContent>
          <TabsContent value="deroule"><TabDeroule ev={ev} write={can("events:write")} /></TabsContent>
          <TabsContent value="documents"><DocumentsTab {...props} /></TabsContent>
          <TabsContent value="portail"><PortalTab ev={ev} /></TabsContent>
          <TabsContent value="musique"><EventMusic ev={ev} /></TabsContent>
          {can("comms:view") && <TabsContent value="communication"><EventComm eid={ev.id} /></TabsContent>}
          {can("providers:manage") && <TabsContent value="staff"><StaffTab ev={ev} /></TabsContent>}
          {can("finance:read") && <TabsContent value="finances"><FinancesTab {...props} /></TabsContent>}
          <TabsContent value="historique"><HistoryTab {...props} /></TabsContent>
        </div>
      </Tabs>
      <AlertDialog open={!!shortAsk} onOpenChange={(o) => !o && setShortAsk(null)}>
        <AlertDialogContent data-testid="shortage-confirm-dialog">
          <AlertDialogHeader><AlertDialogTitle>Matériel manquant aux dates de l'événement</AlertDialogTitle><AlertDialogDescription data-testid="shortage-confirm-summary">{shortAsk?.summary}</AlertDialogDescription></AlertDialogHeader>
          <AlertDialogFooter><AlertDialogCancel>Annuler</AlertDialogCancel><AlertDialogAction data-testid="shortage-confirm-button" onClick={() => { setShortAsk(null); doStatus("confirme"); }}>Confirmer et créer la liste des manques</AlertDialogAction></AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
      <EventFormDialog open={edit} onOpenChange={setEdit} event={ev} onSaved={() => load()} />
      <AlertDialog open={del} onOpenChange={setDel}>
        <AlertDialogContent>
          <AlertDialogHeader><AlertDialogTitle>Supprimer {ev.code} ?</AlertDialogTitle><AlertDialogDescription>L'événement part dans la Corbeille pendant 30 jours (restaurable) et libère le matériel réservé.</AlertDialogDescription></AlertDialogHeader>
          <AlertDialogFooter><AlertDialogCancel>Annuler</AlertDialogCancel><AlertDialogAction data-testid="confirm-delete-event" onClick={remove}>Supprimer</AlertDialogAction></AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}

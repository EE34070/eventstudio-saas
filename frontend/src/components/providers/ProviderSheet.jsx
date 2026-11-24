import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { toast } from "sonner";
import { Pencil, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Info, Loading } from "@/components/common";
import { UploadButton, openFile } from "@/lib/files";
import { api, errMsg } from "@/lib/api";
import { TrashDialog } from "@/components/Trash";
import { fmtDate, fmtEur2 } from "@/lib/constants";
import { PlannerEvents } from "@/components/providers/PlannerEvents";
import { Badge, LEGAL, M_STATUS, NOT_SUBJECT, P_STATUS, REPLY, equipText, priceLabel, travelLabel } from "@/components/providers/shared";

const DOCS = { contrat: "Contrat cadre", kbis: "Kbis / SIRET", urssaf: "Attestation URSSAF de vigilance", rc_pro: "Assurance RC Pro", autre: "Autre" };
const SRC = { manual: "Saisie", request_reply: "Réponse « Pas dispo »", mission: "Mission confirmée" };
const Block = ({ title, children, testid }) => <div className="rounded-2xl border border-border p-4" data-testid={testid}><div className="eyebrow mb-3">{title}</div>{children}</div>;

export function ProviderSheet({ id, onClose, onEdit, categories, version, initialTab }) {
  const [trash, setTrash] = useState(false);
  const [p, setP] = useState(null);
  const [doc, setDoc] = useState({ type: "urssaf", expires_at: "" });
  const [day, setDay] = useState("");
  const [tab, setTab] = useState("fiche");
  useEffect(() => { setTab(initialTab || "fiche"); }, [id, initialTab]);
  const load = useCallback(() => (id ? api.get(`/providers/${id}`).then((r) => setP(r.data)).catch((e) => { toast.error(errMsg(e)); onClose(); }) : setP(null)), [id]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { setP(null); load(); }, [load, version]);
  const run = async (fn) => { try { await fn(); load(); } catch (e) { toast.error(errMsg(e)); } };
  const today = new Date().toISOString().slice(0, 10);
  const soon = new Date(Date.now() + 30 * 86400000).toISOString().slice(0, 10);
  const lab = Object.fromEntries(categories.map((c) => [c.key, c.label]));
  const subject = p?.vat_mode === "subject";
  return (
    <Dialog open={!!id} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-h-[92vh] max-w-4xl overflow-y-auto" data-testid="provider-sheet">
        {!p ? <Loading /> : (<>
          <DialogHeader>
            <DialogTitle className="flex flex-wrap items-center gap-3 font-display text-2xl font-medium"><span data-testid="provider-sheet-name">{p.display_name}</span>
              <Badge tone={{ active: "ok", test: "warn", blocked: "bad" }[p.status]}>{P_STATUS[p.status]}</Badge>
              <Button size="sm" variant="destructive" onClick={() => setTrash(true)} data-testid="provider-delete">Supprimer</Button>{trash && <TrashDialog items={[{ kind: "provider", id }]} onClose={() => setTrash(false)} onDone={() => window.location.reload()} />}<Button size="sm" variant="outline" onClick={() => api.post(`/providers/${id}/invite`).then((r) => (r.data.sent ? toast.success("Invitation envoyée") : window.prompt("E-mail non envoyé. Lien à transmettre :", r.data.link))).catch((e) => toast.error(e.response?.data?.detail || "Invitation impossible"))} data-testid="provider-sheet-invite">Inviter maintenant</Button>
              <Button size="sm" variant="outline" onClick={() => onEdit(p)} data-testid="provider-sheet-edit"><Pencil />Modifier</Button></DialogTitle>
            <p className="text-sm text-muted-foreground">{p.categories.map((c) => lab[c] || c).join(" · ")}{p.tags.length ? ` — ${p.tags.join(", ")}` : ""}</p>
          </DialogHeader>
          {p.categories.some((k) => categories.find((c) => c.key === k)?.is_organizer) && <div className="flex gap-1.5">{[["fiche", "Fiche"], ["events", "Événements apportés"]].map(([k, l]) => <button key={k} onClick={() => setTab(k)} data-testid={`provider-sheet-tab-${k}`}
            className={`h-9 rounded-full border px-4 text-sm font-medium ${tab === k ? "border-primary bg-primary text-white" : "border-border hover:bg-secondary"}`}>{l}</button>)}</div>}
          {tab === "events" ? <PlannerEvents providerId={p.id} /> : (<>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4" data-testid="provider-conditions">
            <Block title="1. Prix"><div className="text-sm font-semibold">{fmtEur2(p.base_rate)} {subject ? "HT" : "net"}</div><div className="text-xs text-muted-foreground">{p.included_hours} h incluses · heure sup. {fmtEur2(p.extra_hour_rate)}</div></Block>
            <Block title="2. Déplacement"><div className="text-sm font-semibold">{travelLabel(p)}</div><div className="text-xs text-muted-foreground">{p.meal_lodging ? `Défraiement fin tardive : ${fmtEur2(p.meal_lodging_fee)}` : "Pas de défraiement"}</div></Block>
            <Block title="3. TVA"><div className="text-sm font-semibold">{subject ? `Assujetti — ${String(p.vat_rate).replace(".", ",")} %, soit ${fmtEur2(p.base_rate * (1 + p.vat_rate / 100))} TTC` : NOT_SUBJECT}</div><div className="text-xs text-muted-foreground">{LEGAL[p.legal_status]}</div></Block>
            <Block title="4. Matériel"><div className="text-sm">Apporte : {p.equipment_brought || "—"}</div><div className="text-sm">À fournir : {equipText(p.equipment_needed) || "rien"}{p.equipment_needed_note ? ` (${p.equipment_needed_note})` : ""}</div>
              {p.tech_rider && <button className="text-xs underline" onClick={() => openFile(p.tech_rider)}>Fiche technique</button>}</Block>
          </div>
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
            <Info label="E-mail" value={p.email} /><Info label="Téléphone" value={`${p.phone}${p.whatsapp ? " (WhatsApp)" : ""}`} />
            <Info label="Zone" value={[p.base_city && `${p.base_city} + ${p.radius_km} km`, p.departments.length && `dép. ${p.departments.join(", ")}`, p.travels_everywhere && "se déplace partout"].filter(Boolean).join(" · ")} />
            <Info label="Langues" value={p.languages.join(", ")} />
            <Info label="Note" value={p.rating ? `${p.rating} / 5` : "Non noté"} />
            <Info label="Fiabilité" value={p.response_rate == null ? "Aucune demande envoyée" : `${p.response_rate} % de réponses${p.avg_response_time_min != null ? ` · délai moyen ${p.avg_response_time_min < 120 ? `${p.avg_response_time_min} min` : `${Math.round(p.avg_response_time_min / 60)} h`}` : ""}`} />
            <Info label="Liens" value={[p.website, p.instagram, p.video_url].filter(Boolean).join(" · ")} /><Info label="Notes privées" value={p.notes} />
          </div>
          <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
            <Block title="Documents" testid="provider-documents">
              {p.documents.map((d) => (
                <div key={d.id} className="mb-2 flex items-center gap-2 text-sm" data-testid={`provider-doc-${d.id}`}>
                  <button className="min-w-0 flex-1 truncate text-left underline" onClick={() => openFile(d.file)}>{DOCS[d.type]}</button>
                  {d.expires_at && <Badge tone={d.expires_at < today ? "bad" : d.expires_at <= soon ? "warn" : "muted"} testid="provider-doc-expiry">{d.expires_at < today ? "Expiré le" : "Expire le"} {fmtDate(d.expires_at)}</Badge>}
                  <button title="Supprimer" onClick={() => window.confirm("Supprimer ce document ?") && run(() => api.delete(`/provider-documents/${d.id}`))}><Trash2 className="h-4 w-4" /></button>
                </div>
              ))}
              <div className="mt-3 flex flex-wrap items-center gap-2">
                <Select value={doc.type} onValueChange={(v) => setDoc({ ...doc, type: v })}><SelectTrigger className="h-8 w-56 text-xs" data-testid="provider-doc-type"><SelectValue /></SelectTrigger><SelectContent>{Object.entries(DOCS).map(([k, l]) => <SelectItem key={k} value={k}>{l}</SelectItem>)}</SelectContent></Select>
                <Input type="date" className="h-8 w-40 text-xs" value={doc.expires_at} onChange={(e) => setDoc({ ...doc, expires_at: e.target.value })} title="Date d'expiration" data-testid="provider-doc-expires" />
                <UploadButton multiple={false} testid="provider-doc-upload" onUploaded={(r) => run(() => api.post(`/providers/${id}/documents`, { ...doc, file: r[0] }))} />
              </div>
            </Block>
            <Block title="Indisponibilités et missions" testid="provider-unavailabilities">
              {!p.unavailabilities.length && <p className="text-sm text-muted-foreground">Aucune date connue.</p>}
              {p.unavailabilities.slice(0, 12).map((u) => (
                <div key={u.id} className="mb-1.5 flex items-center gap-2 text-sm"><span className="flex-1">{fmtDate(u.date)}{u.start_time ? ` · ${u.start_time}–${u.end_time}` : ""}</span><Badge tone={u.source === "mission" ? "info" : "muted"}>{SRC[u.source]}</Badge>
                  {u.source !== "mission" && <button title="Supprimer" onClick={() => run(() => api.delete(`/provider-unavailabilities/${u.id}`))}><Trash2 className="h-4 w-4" /></button>}</div>
              ))}
              <div className="mt-3 flex items-center gap-2"><Input type="date" className="h-8 w-40 text-xs" value={day} onChange={(e) => setDay(e.target.value)} data-testid="provider-unavail-date" />
                <Button size="sm" variant="outline" disabled={!day} onClick={() => run(async () => { await api.post(`/providers/${id}/unavailabilities`, { date: day }); setDay(""); })} data-testid="provider-unavail-add">Ajouter une indisponibilité</Button></div>
            </Block>
          </div>
          <Block title="Historique des demandes et missions" testid="provider-history">
            {!p.history.length && <p className="text-sm text-muted-foreground">Aucune demande envoyée.</p>}
            {p.history.map((h, i) => {
              const m = p.missions.find((x) => x.request_id === h.request_id);
              return <Link key={i} to={`/prestataires/demandes/${h.request_id}`} className="flex flex-wrap items-center gap-2 border-b border-border py-2 text-sm last:border-b-0 hover:underline">
                <span className="flex-1">{h.category} · {fmtDate(h.date)} · {h.city}</span><Badge>{REPLY[h.status]}</Badge>{m && <Badge tone="info">Mission {M_STATUS[m.status].toLowerCase()}</Badge>}
                {h.total_ttc != null && <span className="text-xs text-muted-foreground">{priceLabel(h.vat_mode, h.total_ht, h.total_ttc)}</span>}</Link>;
            })}
          </Block>
          </>)}
        </>)}
      </DialogContent>
    </Dialog>
  );
}

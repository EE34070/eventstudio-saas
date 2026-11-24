import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { toast } from "sonner";
import { ArrowLeft, Pencil, Plus, Send } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Switch } from "@/components/ui/switch";
import { Field, Loading, Section } from "@/components/common";
import { api, errMsg } from "@/lib/api";
import { fmtDate, fmtEur2 } from "@/lib/constants";
import { Badge, EQUIP, R_STATUS, REPLY, equipText, priceLabel } from "@/components/providers/shared";
import { ProviderDialog } from "@/components/providers/ProviderDialog";
import { RequestDialog } from "@/components/providers/RequestDialog";

const th = "px-3 py-2.5 text-left text-xs font-semibold text-muted-foreground";
const td = "px-3 py-2.5 align-top";
const when = (iso) => (iso ? new Date(iso).toLocaleString("fr-FR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" }) : "—");
const TONE = { retained: "ok", available: "ok", conditional: "warn", unavailable: "bad", error: "bad" };
const NOFILTER = { tags: "", lang: "", cost: "", dist: "", vat: "all", all: false };

export default function DemandePrestataire() {
  const { id } = useParams();
  const [req, setReq] = useState(null);
  const [cands, setCands] = useState(null);
  const [cats, setCats] = useState([]);
  const [sel, setSel] = useState([]);
  const [flt, setFlt] = useState(NOFILTER);
  const [msg, setMsg] = useState(null);
  const [cascade, setCascade] = useState({ on: false, size: 3, delay: 24 });
  const [preview, setPreview] = useState(null);
  const [dialog, setDialog] = useState(null);
  const [busy, setBusy] = useState("");
  const [inact, setInact] = useState(false);
  const load = useCallback(() => {
    api.get(`/service-requests/${id}`).then((r) => { setReq(r.data); setMsg((m) => m || r.data.message); }).catch((e) => toast.error(errMsg(e)));
    api.get(`/service-requests/${id}/candidates`, { params: { inactive: inact } }).then((r) => setCands(r.data)).catch(() => {});
  }, [id, inact]);
  useEffect(() => { load(); api.get("/provider-categories").then((r) => setCats(r.data)).catch(() => {}); const t = setInterval(load, 20000); return () => clearInterval(t); }, [load]);
  if (!req || !cands || !msg) return <Loading />;

  const open = !["filled", "cancelled"].includes(req.status);
  const shown = cands.filter((c) => !c.already_sent && (flt.all || c.match)
    && (!flt.tags || c.tags.join(" ").toLowerCase().includes(flt.tags.toLowerCase())) && (!flt.lang || c.languages.join(" ").toLowerCase().includes(flt.lang.toLowerCase()))
    && (!flt.cost || c.total_ttc <= Number(flt.cost)) && (!flt.dist || (c.distance_km != null && c.distance_km <= Number(flt.dist))) && (flt.vat === "all" || c.vat_mode === flt.vat));
  const ids = shown.map((c) => c.id);
  const picked = sel.filter((x) => ids.includes(x));
  const run = async (key, fn, ok) => { setBusy(key); try { await fn(); if (ok) toast.success(ok); load(); } catch (e) { toast.error(errMsg(e)); } setBusy(""); };
  const send = () => run("send", async () => {
    const r = await api.post(`/service-requests/${id}/send`, { provider_ids: picked, subject: msg.subject, body: msg.body, app_url: window.location.origin, cascade_enabled: cascade.on, cascade_batch_size: Number(cascade.size) || 1, cascade_delay_h: Number(cascade.delay) || 24 });
    setReq(r.data); setSel([]);
  }, cascade.on ? "Envoi en cascade lancé" : "Demandes en cours d'envoi");
  const retain = (r) => {
    const miss = r.missing_equipment.length ? `\n\nAttention, matériel à prévoir (absent sur place) : ${equipText(r.missing_equipment)}.` : "";
    if (!window.confirm(`Retenir ${r.display_name} pour ${priceLabel(r.vat_mode, r.total_ht, r.total_ttc)} ?${r.estimated ? "\n\nCe prestataire n'a pas répondu : montants estimés d'après sa fiche." : ""}${miss}\n\nUne confirmation lui sera envoyée par e-mail.`)) return;
    run("retain", async () => { const d = (await api.post(`/service-requests/${id}/recipients/${r.id}/retain${window.confirm("Créer aussi son accès au portail prestataire et lui envoyer l'invitation ?\n\nOK = créer le compte · Annuler = ne pas créer de compte") ? "" : "?no_account=true"}`)).data;
      toast.success(`Mission créée${d.filled ? ` — demande pourvue, ${d.notified_others} autre(s) prestataire(s) prévenu(s)` : ""}`); if (d.missing_equipment.length) toast.warning(`Matériel à prévoir : ${equipText(d.missing_equipment)}`); });
  };
  const fset = (k) => (e) => setFlt({ ...flt, [k]: e?.target ? e.target.value : e });

  return (
    <div data-testid="request-page">
      <Link to="/prestataires?tab=demandes" className="mb-5 inline-flex items-center gap-1.5 text-xs font-medium text-muted-foreground hover:text-foreground"><ArrowLeft className="h-3.5 w-3.5" />Demandes</Link>
      <div className="card-soft p-6">
        <div className="flex flex-wrap items-start gap-3">
          <div className="min-w-0 flex-1">
            <h1 className="text-3xl font-extrabold tracking-tight" data-testid="request-title">{req.category_label}{req.quantity > 1 ? ` × ${req.quantity}` : ""} — {fmtDate(req.date)}</h1>
            <p className="mt-2 text-sm text-muted-foreground">{req.start_time}–{req.end_time} ({String(req.duration_h).replace(".", ",")} h) · {[req.venue_address, req.venue_zip, req.venue_city].filter(Boolean).join(", ")}{req.event_type ? ` · ${req.event_type}` : ""}{req.guest_count ? ` · ${req.guest_count} invités` : ""}</p>
            <p className="mt-1 text-sm text-muted-foreground">Sur place : {equipText(req.onsite_equipment) || "aucun matériel indiqué"} · Réponse attendue avant le {when(req.reply_deadline)}{req.event_id && <> · <Link className="underline" to={`/evenements/${req.event_id}`}>Voir l'événement</Link></>}</p>
            {req.venue_lat == null && <p className="mt-1 text-sm text-amber-700 dark:text-amber-400" data-testid="request-no-geo">Lieu non localisé : distances et frais au km non calculés. Modifiez l'adresse.</p>}
          </div>
          <Badge tone={{ filled: "ok", cancelled: "bad" }[req.status] || "info"} testid="request-status">{R_STATUS[req.status]}</Badge>
          {open && <Button size="sm" variant="outline" onClick={() => setDialog("request")} data-testid="request-edit-button"><Pencil />Modifier</Button>}
          {open && <Button size="sm" variant="outline" disabled={!!busy} onClick={() => window.confirm("Annuler cette demande ?") && run("cancel", () => api.post(`/service-requests/${id}/cancel`))} data-testid="request-cancel-button">Annuler la demande</Button>}
        </div>
      </div>

      {req.recipients.length > 0 && (
        <Section title="Suivi des réponses" className="mt-5" testid="tracking-section">
          <div className="overflow-x-auto"><table className="w-full min-w-[980px] text-sm" data-testid="tracking-table">
            <thead><tr className="border-b border-border"><th className={th}>Prestataire</th><th className={th}>Statut</th><th className={th}>Prix</th><th className={th}>Déplacement</th><th className={th}>TVA</th><th className={th}>Total comparable TTC</th><th className={th}>Matériel</th><th className={th}>Réponse</th><th className={th} /></tr></thead>
            <tbody>{req.recipients.map((r) => (
              <tr key={r.id} className="border-b border-border last:border-b-0" data-testid={`recipient-row-${r.id}`}>
                <td className={td}><div className="font-semibold">{r.display_name}</div><div className="text-xs text-muted-foreground">{r.email}</div>{r.reply_comment && <div className="mt-1 max-w-xs text-xs">« {r.reply_comment} »</div>}
                  {r.alt_start && <div className="text-xs">Propose {r.alt_start}–{r.alt_end}</div>}{r.send_error && <div className="text-xs text-red-600">{r.send_error}</div>}</td>
                <td className={td}><Badge tone={TONE[r.status] || "muted"} testid={`recipient-status-${r.id}`}>{REPLY[r.status]}</Badge>{r.reminded_at && <div className="mt-1 text-[11px] text-muted-foreground">Relancé le {when(r.reminded_at)}</div>}</td>
                {r.status === "unavailable" ? <td className={td} colSpan={5}><span className="text-muted-foreground">—</span></td> : (<>
                  <td className={td}>{fmtEur2(r.proposed_rate)}{r.estimated && <div className="text-[11px] text-muted-foreground">estimé (fiche)</div>}</td>
                  <td className={td}>{fmtEur2(r.proposed_travel_fee)}</td>
                  <td className={td}>{r.vat_mode === "subject" ? `HT + ${String(r.vat_rate).replace(".", ",")} %` : "Net, TVA non applicable"}</td>
                  <td className={td}><b data-testid={`recipient-ttc-${r.id}`}>{fmtEur2(r.total_ttc)} {r.vat_mode === "subject" ? "TTC" : "net"}</b>{r.vat_mode === "subject" && <div className="text-[11px] text-muted-foreground">{fmtEur2(r.total_ht)} HT</div>}</td>
                  <td className={td}>{r.missing_equipment.length ? <Badge tone="warn" testid={`recipient-equipment-${r.id}`}>À prévoir : {equipText(r.missing_equipment)}</Badge> : <span className="text-muted-foreground">OK</span>}{r.equipment_note && <div className="mt-1 text-[11px]">{r.equipment_note}</div>}</td>
                </>)}
                <td className={td}>{when(r.replied_at)}</td>
                <td className={`${td} whitespace-nowrap text-right`}>
                  {open && ["sent", "opened", "error"].includes(r.status) && <Button size="sm" variant="outline" disabled={!!busy} onClick={() => run("remind", () => api.post(`/service-requests/${id}/recipients/${r.id}/remind`), "Relance envoyée")} data-testid={`recipient-remind-${r.id}`}>Relancer</Button>}
                  {open && !["unavailable", "retained", "queued", "error"].includes(r.status) && <Button size="sm" className="ml-2" disabled={!!busy} onClick={() => retain(r)} data-testid={`recipient-retain-${r.id}`}>Retenir</Button>}
                </td>
              </tr>))}</tbody></table></div>
          {req.missions.map((m) => <p key={m.id} className="mt-3 text-sm" data-testid={`mission-note-${m.id}`}>Mission confirmée avec <b>{m.provider_name}</b> : {priceLabel(m.vat_mode, m.total_ht, m.total_ttc)}.
            {m.confirmation_sent_at ? " Confirmation envoyée." : m.confirmation_error ? ` Confirmation non envoyée : ${m.confirmation_error}` : " Confirmation en cours d'envoi."}{m.missing_equipment.length > 0 && <b className="text-amber-700 dark:text-amber-400"> Matériel à prévoir : {equipText(m.missing_equipment)}.</b>}</p>)}
        </Section>
      )}

      {open && (<>
        <Section title={`Prestataires correspondants (${shown.length})`} className="mt-5" testid="candidates-section"
          actions={<Button size="sm" variant="outline" onClick={() => setDialog("provider")} data-testid="candidates-new-provider"><Plus />Nouveau prestataire</Button>}>
          <div className="mb-3 flex flex-wrap items-end gap-3">
            <Field label="Tag"><Input className="h-8 w-32 text-xs" value={flt.tags} onChange={fset("tags")} data-testid="filter-tags" /></Field>
            <Field label="Langue"><Input className="h-8 w-28 text-xs" value={flt.lang} onChange={fset("lang")} data-testid="filter-lang" /></Field>
            <Field label="Coût max TTC"><Input type="number" className="h-8 w-28 text-xs" value={flt.cost} onChange={fset("cost")} data-testid="filter-cost" /></Field>
            <Field label="Distance max (km)"><Input type="number" className="h-8 w-28 text-xs" value={flt.dist} onChange={fset("dist")} data-testid="filter-distance" /></Field>
            <Field label="Régime TVA"><select className="h-8 rounded-lg border border-border bg-background px-2 text-xs" value={flt.vat} onChange={fset("vat")} data-testid="filter-vat"><option value="all">Tous</option><option value="subject">Assujetti</option><option value="not_applicable_293B">Non assujetti</option></select></Field>
            <label className="flex items-center gap-2 pb-1.5 text-xs"><Switch checked={flt.all} onCheckedChange={fset("all")} data-testid="filter-all" />Afficher aussi les prestataires hors critères</label>
            <label className="flex items-center gap-2 pb-1.5 text-xs"><Switch checked={inact} onCheckedChange={setInact} data-testid="filter-inactive" />Afficher aussi les inactifs</label>
          </div>
          {!shown.length ? <p className="py-6 text-center text-sm text-muted-foreground" data-testid="candidates-empty">Aucun prestataire actif ne correspond à ce métier et à cette zone.</p> : (
            <div className="overflow-x-auto"><table className="w-full min-w-[980px] text-sm" data-testid="candidates-table">
              <thead><tr className="border-b border-border"><th className={th}><input type="checkbox" checked={picked.length === ids.length} onChange={(e) => setSel(e.target.checked ? ids : [])} aria-label="Tout sélectionner" data-testid="candidates-select-all" /></th>
                <th className={th}>Prestataire</th><th className={th}>Distance</th><th className={th}>Coût total estimé</th><th className={th}>Matériel</th><th className={th}>Note</th><th className={th}>Réponses</th><th className={th}>Dernière collaboration</th></tr></thead>
              <tbody>{shown.map((c) => (
                <tr key={c.id} className="border-b border-border last:border-b-0" data-testid={`candidate-row-${c.id}`}>
                  <td className={td}><input type="checkbox" checked={sel.includes(c.id)} disabled={!c.email} onChange={(e) => setSel(e.target.checked ? [...sel, c.id] : sel.filter((x) => x !== c.id))} aria-label={`Sélectionner ${c.display_name}`} data-testid={`candidate-check-${c.id}`} /></td>
                  <td className={td}><div className="font-semibold">{c.display_name}</div><div className="text-xs text-muted-foreground">{c.base_city}{c.tags.length ? ` · ${c.tags.join(", ")}` : ""}</div>
                    <div className="mt-1 flex flex-wrap gap-1">{c.unavailable && <Badge tone="bad" testid={`candidate-unavailable-${c.id}`}>Déjà indisponible</Badge>}{c.on_mission && <Badge tone="bad">Déjà en mission ce jour</Badge>}{c.status === "test" && <Badge tone="warn">En test</Badge>}
                      {!c.match && <Badge>{c.has_category ? "Hors zone" : "Autre métier"}</Badge>}{!c.email && <Badge tone="bad">E-mail manquant</Badge>}</div></td>
                  <td className={td}>{c.distance_km == null ? "—" : `${String(c.distance_km).replace(".", ",")} km`}</td>
                  <td className={td}><b data-testid={`candidate-total-${c.id}`}>{priceLabel(c.vat_mode, c.total_ht, c.total_ttc)}</b><div className="text-[11px] text-muted-foreground">Prix {fmtEur2(c.rate)}{c.extra_hours ? ` (dont ${c.extra_hours} h sup.)` : ""} + déplacement {c.travel_on_quote ? "sur devis" : fmtEur2(c.travel_fee)}</div></td>
                  <td className={td}>{c.missing_equipment.length ? <Badge tone="warn" testid={`candidate-equipment-${c.id}`}>À prévoir : {equipText(c.missing_equipment)}</Badge> : <span className="text-muted-foreground">OK</span>}</td>
                  <td className={td}>{c.rating ? `${c.rating} / 5` : "—"}</td>
                  <td className={td}>{c.response_rate == null ? "—" : `${c.response_rate} %`}</td>
                  <td className={td}>{c.last_collaboration ? fmtDate(c.last_collaboration) : "—"}</td>
                </tr>))}</tbody></table></div>)}
        </Section>

        <Section title={`Message (${picked.length} destinataire(s))`} className="mt-5" testid="send-section">
          <p className="mb-3 text-sm text-muted-foreground">Envoi individuel depuis {req.sender || "— boîte Gmail non connectée —"} : chaque prestataire reçoit son propre lien, sans voir les autres. Variables : {"{prénom} {métier} {date} {horaires} {ville} {type_evenement} {brief} {materiel_sur_place} {budget} {date_limite} {lien_reponse}"}. SMS et WhatsApp : non configurés.</p>
          <Field label="Objet"><Input value={msg.subject} onChange={(e) => setMsg({ ...msg, subject: e.target.value })} data-testid="send-subject" /></Field>
          <Field label="Message" className="mt-3"><Textarea rows={10} value={msg.body} onChange={(e) => setMsg({ ...msg, body: e.target.value })} data-testid="send-body" /></Field>
          <div className="mt-3 flex flex-wrap items-center gap-3 text-sm">
            <label className="flex items-center gap-2"><Switch checked={cascade.on} onCheckedChange={(v) => setCascade({ ...cascade, on: v })} data-testid="send-cascade" />Envoi en cascade</label>
            {cascade.on && <>aux <Input type="number" min={1} className="h-8 w-16" value={cascade.size} onChange={(e) => setCascade({ ...cascade, size: e.target.value })} data-testid="send-cascade-size" /> premiers, puis les suivants si personne n'a accepté après
              <Input type="number" min={1} className="h-8 w-16" value={cascade.delay} onChange={(e) => setCascade({ ...cascade, delay: e.target.value })} data-testid="send-cascade-delay" /> h</>}
          </div>
          <div className="mt-4 flex flex-wrap gap-2">
            <Button variant="outline" disabled={!picked.length || !!busy} onClick={() => run("preview", async () => setPreview((await api.post(`/service-requests/${id}/preview`, { provider_id: picked[0], ...msg })).data))} data-testid="send-preview-button">Aperçu</Button>
            <Button variant="outline" disabled={!!busy} onClick={() => run("tpl", () => api.put("/message-templates", { type: "request", category_key: req.category_key, ...msg }), `Modèle enregistré pour « ${req.category_label} »`)} data-testid="send-save-template">Enregistrer comme modèle de ce métier</Button>
            <Button className="ml-auto" disabled={!picked.length || !req.sender || !!busy} onClick={send} data-testid="send-button"><Send />{busy === "send" ? "Envoi…" : `Envoyer à ${picked.length} prestataire(s)`}</Button>
          </div>
          {preview && <div className="mt-4 rounded-2xl border border-border p-4 text-sm" data-testid="send-preview"><div className="font-semibold">{preview.subject}</div><p className="mt-2 whitespace-pre-wrap">{preview.body}</p></div>}
        </Section>
      </>)}
      <ProviderDialog open={dialog === "provider"} onOpenChange={(o) => setDialog(o ? "provider" : null)} provider={null} categories={cats} onSaved={(p) => { setFlt({ ...flt, all: true }); setSel((s) => [...s, p.id]); load(); }} onOpenExisting={() => {}} />
      <RequestDialog open={dialog === "request"} onOpenChange={(o) => setDialog(o ? "request" : null)} categories={cats} request={req} onSaved={load} />
    </div>
  );
}

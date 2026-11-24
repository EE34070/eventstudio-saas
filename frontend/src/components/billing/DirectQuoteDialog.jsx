import { useEffect, useState } from "react";
import { toast } from "sonner";
import { ArrowDown, ArrowUp, Plus, Trash2 } from "lucide-react";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Field } from "@/components/common";
import { api, errMsg } from "@/lib/api";
import { EVENT_TYPES, fmtEur2 } from "@/lib/constants";
import { LanguageSelect } from "@/lib/i18n";
import { VenueField, venueDraftOk } from "@/components/events/VenueField";
import { AvailabilityPanel, DOT } from "@/components/stock/Availability";
import { dual, toPieces, uomLabel, uomOf } from "@/components/catalogue/Units";

const sel = "h-10 w-full rounded-lg border border-border bg-background px-3 text-sm";
const KINDS = { service: "Prestation libre", catalog: "Produit du catalogue", pack: "Pack", title: "Titre / section", discount: "Remise", fee: "Frais (déplacement…)" };
const LINE = { kind: "service", label: "", description: "", qty: 1, unit: "", unit_price: 0, vat: 20, equipment_id: "", pack_id: "" };
const EMPTY = { event_id: "", client_id: "", new_client: null, organizer_contact_id: "", type: "Mariage", date: "", venue_id: "", guests: 0, language: "", deposit_percent: 30, valid_until: "", notes: "", lines: [{ ...LINE }] };

export function DirectQuoteDialog({ open, onOpenChange, onSaved, preset }) {
  const [f, setF] = useState(EMPTY);
  const [nv, setNv] = useState(null);
  const [refs, setRefs] = useState({ contacts: [], venues: [], organizers: [], events: [], equipment: [], packs: [] });
  const [busy, setBusy] = useState(false);
  const [tpls, setTpls] = useState([]);
  const [tpl, setTpl] = useState("");
  useEffect(() => { if (open) { setTpl(""); api.get("/quote-templates").then((r) => setTpls(r.data)).catch(() => {}); } }, [open]);
  const fromTpl = async () => { setBusy(true); try { const r = await api.post(`/quote-templates/${tpl}/use`, { event_id: f.event_id }); r.data.warnings.forEach((w) => toast.warning(w)); toast.success(`Devis ${r.data.number} créé à partir du modèle`); onSaved?.(r.data); onOpenChange(false); } catch (e) { toast.error(errMsg(e)); } setBusy(false); };
  const [av, setAv] = useState(null);
  const [showAv, setShowAv] = useState(true);
  const [tick, setTick] = useState(0);
  useEffect(() => {
    if (!open) return;
    setF({ ...EMPTY, lines: [{ ...LINE }], ...preset }); setNv(null);
    const get = (p) => api.get(p).then((r) => r.data).catch(() => []);
    Promise.all([get("/contacts?type=client"), get("/venues"), get("/organizers"), get("/events"), get("/packs")]).then(([contacts, venues, organizers, events, packs]) => setRefs((r) => ({ ...r, contacts, venues, organizers, events: events.filter((e) => e.status !== "cloture"), packs })));
  }, [open, preset]);
  useEffect(() => {
    if (!open) return;
    const params = f.date ? { start: `${f.date}T00:00`, end: `${f.date}T23:59` } : {};
    api.get("/equipment", { params }).then((r) => setRefs((x) => ({ ...x, equipment: r.data.items || [] }))).catch(() => {});
  }, [open, f.date]);
  const stockKey = JSON.stringify([f.event_id, f.date, f.venue_id, f.lines.filter((l) => (l.kind === "catalog" && l.equipment_id) || (l.kind === "pack" && l.pack_id)).map((l) => [l.equipment_id, l.pack_id, l.qty, l.uom || ""])]);
  useEffect(() => {
    if (!open) return undefined;
    const [event_id, date, venue_id, ls] = JSON.parse(stockKey);
    if (!ls.length) { setAv(null); return undefined; }
    const t = setTimeout(() => api.post("/stock/availability", { event_id, date, venue_id, lines: ls.map(([equipment_id, pack_id, qty, uom]) => ({ equipment_id: equipment_id || "", pack_id: pack_id || "", qty: Number(qty) || 1, uom: uom || "" })) }).then((r) => setAv(r.data)).catch(() => setAv(null)), 400);
    return () => clearTimeout(t);
  }, [open, stockKey, tick]);
  const set = (k) => (e) => setF({ ...f, [k]: e?.target ? e.target.value : e });
  const upd = (i, patch) => setF({ ...f, lines: f.lines.map((l, j) => (j === i ? { ...l, ...patch } : l)) });
  const move = (i, d) => { const lines = [...f.lines]; [lines[i], lines[i + d]] = [lines[i + d], lines[i]]; setF({ ...f, lines }); };
  const pickItem = (i, l, id) => {
    if (l.kind === "catalog") { const eq = refs.equipment.find((x) => x.id === id); upd(i, { equipment_id: id, label: eq ? `${eq.ref} ${eq.name}` : "", ...uomOf(eq, eq?.quote_uom === "secondary" ? "secondary" : "") }); }
    else { const p = refs.packs.find((x) => x.id === id); upd(i, { pack_id: id, label: p?.name || "", description: p?.description || "", unit_price: p?.price || 0 }); }
  };
  const priced = f.lines.filter((l) => l.kind !== "title");
  const amount = (l) => (Number(l.qty) || 0) * (Number(l.unit_price) || 0) * (l.kind === "discount" ? -1 : 1);
  const ht = priced.reduce((n, l) => n + amount(l), 0);
  const vat = priced.reduce((n, l) => n + (amount(l) * (Number(l.vat) || 0)) / 100, 0);
  const submit = async () => {
    if (nv && !venueDraftOk(nv)) return toast.error("Complétez les champs obligatoires du nouveau lieu");
    setBusy(true);
    const lines = f.lines.filter((l) => l.label.trim()).map((l) => ({ label: l.label, description: l.description || "", kind: l.kind, unit: l.unit || "", uom: l.kind === "catalog" ? l.uom || "" : "", qty: l.kind === "title" ? 1 : Number(l.qty) || 1,
      unit_price: l.kind === "title" ? 0 : Math.abs(Number(l.unit_price) || 0) * (l.kind === "discount" ? -1 : 1), vat: Number(l.vat) || 0, equipment_id: l.kind === "catalog" ? l.equipment_id : "", pack_id: l.kind === "pack" ? l.pack_id : "" }));
    const body = { event_id: f.event_id, client_ids: f.client_id && f.client_id !== "new" ? [f.client_id] : [], new_client: f.client_id === "new" ? f.new_client : null, organizer_contact_id: f.organizer_contact_id, type: f.type, date: f.date,
      venue_id: nv ? "" : f.venue_id, new_venue: nv || null, guests: Number(f.guests) || 0, language: f.language, lines, deposit_percent: Number(f.deposit_percent) || 0, valid_until: f.valid_until, notes: f.notes };
    try { const r = await api.post("/quotes/direct", body); toast.success(`Devis ${r.data.number} créé — événement ${r.data.event_code} ${f.event_id ? "rattaché" : "créé"}`); onSaved?.(r.data); onOpenChange(false); } catch (e) { toast.error(errMsg(e)); }
    setBusy(false);
  };
  const nc = f.new_client || { first_name: "", last_name: "", company: "", email: "", phone: "", language: "fr-FR" };
  const setNc = (k) => (e) => setF({ ...f, new_client: { ...nc, [k]: e?.target ? e.target.value : e } });
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[92vh] max-w-4xl overflow-y-auto" data-testid="direct-quote-dialog">
        <DialogHeader><DialogTitle className="text-xl font-bold">Nouveau devis</DialogTitle></DialogHeader>
        {tpls.length > 0 && <div className="flex flex-wrap items-center gap-2 rounded-2xl border border-border p-3" data-testid="dq-template"><span className="text-sm font-semibold">À partir d'un modèle</span><select className={`${sel} max-w-xs`} value={tpl} onChange={(e) => setTpl(e.target.value)} data-testid="dq-template-select"><option value="">— Aucun —</option>{tpls.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}</select><Button type="button" size="sm" disabled={!tpl || busy} onClick={fromTpl} data-testid="dq-template-use">Créer depuis ce modèle</Button><span className="text-xs text-muted-foreground">Client et dates repris de l'événement choisi ci-dessous (ou sans événement).</span></div>}
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <Field label="Rattacher à un événement existant (sinon il est créé automatiquement)" className="sm:col-span-2">
            <select className={sel} value={f.event_id} onChange={set("event_id")} data-testid="dq-event"><option value="">— Créer un nouvel événement « Demande » —</option>{refs.events.map((e) => <option key={e.id} value={e.id}>{e.code} · {e.title}</option>)}</select></Field>
          {!f.event_id && (<>
            <Field label="Client"><select className={sel} value={f.client_id} onChange={set("client_id")} data-testid="dq-client"><option value="">— Choisir —</option><option value="new">+ Créer un client</option>{refs.contacts.map((c) => <option key={c.id} value={c.id}>{c.display_name}</option>)}</select></Field>
            <Field label="Organisateur (optionnel)"><select className={sel} value={f.organizer_contact_id} onChange={set("organizer_contact_id")} data-testid="dq-organizer"><option value="">— Aucun —</option>{refs.organizers.map((o) => <option key={o.contact_id} value={o.contact_id}>{o.display_name}</option>)}</select></Field>
            {f.client_id === "new" && <div className="grid grid-cols-2 gap-2 rounded-2xl border border-border p-3 sm:col-span-2" data-testid="dq-new-client">
              <Input placeholder="Prénom" value={nc.first_name} onChange={setNc("first_name")} data-testid="dq-client-first" /><Input placeholder="Nom" value={nc.last_name} onChange={setNc("last_name")} data-testid="dq-client-last" />
              <Input placeholder="Société" value={nc.company} onChange={setNc("company")} /><Input type="email" placeholder="E-mail" value={nc.email} onChange={setNc("email")} data-testid="dq-client-email" />
              <Input placeholder="Téléphone" value={nc.phone} onChange={setNc("phone")} /><LanguageSelect value={nc.language} onChange={setNc("language")} testid="dq-client-language" /></div>}
            <Field label="Type d'événement"><select className={sel} value={f.type} onChange={set("type")} data-testid="dq-type">{EVENT_TYPES.map((t) => <option key={t}>{t}</option>)}</select></Field>
            <Field label="Date (vide = date non fixée)"><Input type="date" value={f.date} onChange={set("date")} data-testid="dq-date" /></Field>
            <VenueField label="Lieu" testid="dq-venue" venues={refs.venues} value={f.venue_id} onChange={set("venue_id")} draft={nv} onDraft={setNv} />
            <Field label="Invités"><Input type="number" min="0" value={f.guests} onChange={set("guests")} data-testid="dq-guests" /></Field>
            <Field label="Langue du devis"><LanguageSelect auto="Langue du client" value={f.language} onChange={set("language")} testid="dq-language" /></Field>
          </>)}
        </div>
        <div className="space-y-2" data-testid="dq-lines">
          {f.lines.map((l, i) => {
            const eq = l.kind === "catalog" && refs.equipment.find((x) => x.id === l.equipment_id);
            const sec = eq && eq.secondary_uom && eq.qty_per_piece;
            const ok = eq && eq.available >= (l.uom === "secondary" && sec ? toPieces(eq, l.qty) : Number(l.qty) || 0);
            return (
              <div key={i} className="grid grid-cols-12 gap-2 rounded-2xl border border-border p-3" data-testid={`dq-line-${i}`}>
                {av?.rows?.find((r) => r.product_id === l.equipment_id && l.kind === "catalog") && <button type="button" onClick={() => setShowAv(true)} className="col-span-12 flex items-center gap-1.5 text-xs" data-testid={`dq-line-badge-${i}`}><span className={`h-2.5 w-2.5 rounded-full ${DOT[av.rows.find((r) => r.product_id === l.equipment_id).color]}`} />Disponibilité</button>}
                <select className={`${sel} col-span-6 sm:col-span-3`} value={l.kind} onChange={(e) => upd(i, { kind: e.target.value })} data-testid={`dq-line-kind-${i}`}>{Object.entries(KINDS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select>
                {["catalog", "pack"].includes(l.kind) && <select className={`${sel} col-span-6 sm:col-span-4`} value={l.kind === "catalog" ? l.equipment_id : l.pack_id} onChange={(e) => pickItem(i, l, e.target.value)} data-testid={`dq-line-item-${i}`}><option value="">— Choisir —</option>{(l.kind === "catalog" ? refs.equipment : refs.packs).map((x) => <option key={x.id} value={x.id}>{x.ref ? `${x.ref} ` : ""}{x.name}</option>)}</select>}
                <Input className={`col-span-12 ${["catalog", "pack"].includes(l.kind) ? "sm:col-span-5" : "sm:col-span-9"}`} placeholder="Libellé" value={l.label} onChange={(e) => upd(i, { label: e.target.value })} data-testid={`dq-line-label-${i}`} />
                {l.kind !== "title" && (<>
                  <Input className="col-span-12 sm:col-span-4" placeholder="Description" value={l.description} onChange={(e) => upd(i, { description: e.target.value })} />
                  <Input type="number" min="0.01" step="any" className="col-span-3 sm:col-span-2" title="Quantité" value={l.qty} onChange={(e) => upd(i, { qty: e.target.value })} data-testid={`dq-line-qty-${i}`} />
                  {sec ? <select className={`${sel} col-span-3 sm:col-span-1`} value={l.uom || ""} onChange={(e) => upd(i, uomOf(eq, e.target.value))} aria-label="Unité" data-testid={`dq-line-uom-${i}`}><option value="">{uomLabel(eq.stock_uom, 1)}</option><option value="secondary">{eq.secondary_uom}</option></select> : <Input className="col-span-3 sm:col-span-1" placeholder="Unité" value={l.unit} onChange={(e) => upd(i, { unit: e.target.value })} />}
                  {sec && l.uom === "secondary" && <span className="col-span-12 text-xs text-muted-foreground" data-testid={`dq-line-conv-${i}`}>{l.qty} {eq.secondary_uom} → {dual(eq, toPieces(eq, l.qty))} réservés</span>}
                  <Input type="number" step="any" className="col-span-3 sm:col-span-2" title="Prix unitaire HT" value={l.unit_price} onChange={(e) => upd(i, { unit_price: e.target.value })} data-testid={`dq-line-price-${i}`} />
                  <select className={`${sel} col-span-3 sm:col-span-1`} title="TVA" value={l.vat} onChange={(e) => upd(i, { vat: e.target.value })}>{[20, 10, 5.5, 0].map((v) => <option key={v} value={v}>{String(v).replace(".", ",")} %</option>)}</select>
                </>)}
                <div className="col-span-12 flex items-center gap-2 sm:col-span-2">
                  <button type="button" disabled={i === 0} onClick={() => move(i, -1)} aria-label="Monter"><ArrowUp className="h-4 w-4" /></button>
                  <button type="button" disabled={i === f.lines.length - 1} onClick={() => move(i, 1)} aria-label="Descendre"><ArrowDown className="h-4 w-4" /></button>
                  <button type="button" disabled={f.lines.length === 1} onClick={() => setF({ ...f, lines: f.lines.filter((_, j) => j !== i) })} aria-label="Supprimer" data-testid={`dq-line-remove-${i}`}><Trash2 className="h-4 w-4" /></button>
                </div>
                {eq && <div className={`col-span-12 text-xs font-medium ${ok ? "text-emerald-600" : "text-amber-600"}`} data-testid={`dq-line-stock-${i}`}>{eq.available} dispo sur {eq.qty_total}{f.date ? " à cette date" : " actuellement"}{ok ? "" : " — stock insuffisant (non bloquant)"}</div>}
              </div>
            );
          })}
          <Button type="button" size="sm" variant="outline" onClick={() => setF({ ...f, lines: [...f.lines, { ...LINE }] })} data-testid="dq-add-line"><Plus />Ligne</Button>
        </div>
        {av && <div className="rounded-2xl border border-border p-3" data-testid="dq-availability"><button type="button" className="flex w-full items-center justify-between text-sm font-semibold" onClick={() => setShowAv(!showAv)} data-testid="dq-availability-toggle">Disponibilité & devis concurrents<span className="text-xs font-normal text-muted-foreground">{showAv ? "Replier" : "Afficher"}</span></button>{showAv && <div className="mt-3"><AvailabilityPanel data={av} onReload={() => setTick((n) => n + 1)} /></div>}</div>}
        <div className="grid grid-cols-2 gap-4">
          <Field label="Acompte à la commande (%)"><Input type="number" min="0" max="99" value={f.deposit_percent} onChange={set("deposit_percent")} data-testid="dq-deposit" /></Field>
          <Field label="Valable jusqu'au (défaut : 30 jours)"><Input type="date" value={f.valid_until} onChange={set("valid_until")} /></Field>
          <Field label="Conditions / notes (visibles sur le PDF)" className="col-span-2"><Textarea rows={2} value={f.notes} onChange={set("notes")} /></Field>
        </div>
        <div className="ml-auto w-full max-w-xs text-sm" data-testid="dq-totals">
          <div className="flex justify-between py-1 text-muted-foreground"><span>Total HT</span><span>{fmtEur2(ht)}</span></div>
          <div className="flex justify-between py-1 text-muted-foreground"><span>TVA</span><span>{fmtEur2(vat)}</span></div>
          <div className="flex justify-between border-t border-border py-2 font-bold"><span>Total TTC</span><span data-testid="dq-total-ttc">{fmtEur2(ht + vat)}</span></div>
        </div>
        <DialogFooter><Button disabled={busy || !f.lines.some((l) => l.label.trim())} onClick={submit} data-testid="dq-submit">{busy ? "Enregistrement…" : "Enregistrer le brouillon"}</Button></DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

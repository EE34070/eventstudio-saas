import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import readXlsxFile from "read-excel-file/browser";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog";
import { api, errMsg } from "@/lib/api";
import { TranslateButton } from "@/lib/i18n";

const TARGETS = [["name", "Nom complet", "nom"], ["first_name", "Prénom", "prenom"], ["last_name", "Nom de famille", "famille"], ["stage_name", "Nom de scène", "scene"], ["company", "Société", "societe"],
  ["email", "E-mail", "mail"], ["phone", "Téléphone", "tel"], ["categories", "Métiers", "metier"], ["tags", "Tags", "tag"], ["base_city", "Ville de base", "ville"], ["base_zip", "Code postal", "postal"],
  ["radius_km", "Rayon (km)", "rayon"], ["departments", "Départements", "depart"], ["travels_everywhere", "Se déplace partout", "partout"], ["base_rate", "Tarif de base", "tarif"],
  ["included_hours", "Heures incluses", "incluses"], ["extra_hour_rate", "Heure supplémentaire", "supp"], ["travel_fee_mode", "Mode de déplacement", "deplacement"],
  ["travel_fee_amount", "Montant déplacement", "montant"], ["travel_km_included", "Km inclus", "km inclus"], ["vat", "TVA (assujetti / non)", "tva"], ["legal_status", "Statut juridique", "statut"],
  ["equipment_brought", "Matériel apporté", "materiel"], ["languages", "Langues", "langue"], ["notes", "Notes", "note"]];
const norm = (s) => String(s || "").normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase();

const parseCsv = (text) => {
  const sep = (text.split("\n")[0].match(/;/g) || []).length >= (text.split("\n")[0].match(/,/g) || []).length ? ";" : ",";
  const rows = [[]]; let cell = ""; let q = false;
  for (let i = 0; i < text.length; i += 1) {
    const ch = text[i];
    if (q) { if (ch === '"' && text[i + 1] === '"') { cell += '"'; i += 1; } else if (ch === '"') q = false; else cell += ch; }
    else if (ch === '"') q = true;
    else if (ch === sep) { rows[rows.length - 1].push(cell); cell = ""; }
    else if (ch === "\n") { rows[rows.length - 1].push(cell); cell = ""; rows.push([]); }
    else if (ch !== "\r") cell += ch;
  }
  rows[rows.length - 1].push(cell);
  return rows;
};

export function ImportDialog({ open, onOpenChange, onDone }) {
  const input = useRef(null);
  const [data, setData] = useState(null);
  const [map, setMap] = useState({});
  const [res, setRes] = useState(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => { if (open) { setData(null); setRes(null); } }, [open]);
  const pick = async (e) => {
    const file = e.target.files[0];
    e.target.value = "";
    if (!file) return;
    try {
      const raw = /\.xlsx$/i.test(file.name) ? await readXlsxFile(file) : parseCsv((await file.text()).replace(/^\ufeff/, ""));
      const rows = raw.map((r) => r.map((c) => (c == null ? "" : String(c).trim()))).filter((r) => r.some(Boolean));
      if (rows.length < 2) { toast.error("Fichier vide"); return; }
      const used = new Set();
      setMap(Object.fromEntries(rows[0].map((h, i) => { const t = TARGETS.find(([k, l]) => !used.has(k) && norm(h) === norm(l)) || (norm(h) === "nom" ? TARGETS[rows[0].some((x) => norm(x).includes("prenom")) ? 2 : 0] : TARGETS.slice(1).find(([k, , hint]) => !used.has(k) && norm(h).includes(hint))); if (t) used.add(t[0]); return [i, t ? t[0] : ""]; })));
      setData({ headers: rows[0], rows: rows.slice(1) });
    } catch { toast.error("Fichier illisible (CSV ou .xlsx attendu)"); }
  };
  const submit = async () => {
    setBusy(true);
    const rows = data.rows.map((r) => Object.fromEntries(Object.entries(map).filter(([, k]) => k).map(([i, k]) => [k, r[i] || ""])));
    const out = { created: 0, skipped: [] };
    try {
      for (let i = 0; i < rows.length; i += 100) {
        const r = (await api.post("/providers/import", { rows: rows.slice(i, i + 100) })).data;
        out.created += r.created; out.skipped.push(...r.skipped.map((s) => ({ ...s, row: s.row + i })));
      }
      setRes(out); onDone();
    } catch (e) { toast.error(errMsg(e)); }
    setBusy(false);
  };
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[92vh] max-w-2xl overflow-y-auto" data-testid="import-dialog">
        <DialogHeader><DialogTitle className="font-display text-2xl font-medium">Importer des prestataires</DialogTitle></DialogHeader>
        <input ref={input} type="file" hidden accept=".csv,.xlsx,text/csv" onChange={pick} data-testid="import-file-input" />
        {res ? (
          <div className="text-sm" data-testid="import-result"><p className="font-semibold">{res.created} prestataire(s) créé(s), {res.skipped.length} ligne(s) ignorée(s).</p>
            {res.skipped.slice(0, 30).map((s) => <div key={s.row} className="text-muted-foreground">Ligne {s.row} : {s.reason}</div>)}</div>
        ) : !data ? (
          <div className="text-sm"><p className="text-muted-foreground">Fichier CSV ou Excel (.xlsx), première ligne = titres des colonnes. Vous associez ensuite chaque colonne à un champ. Un métier inconnu est classé dans « Autres » et conservé en tag.</p>
            <Button className="mt-4" onClick={() => input.current.click()} data-testid="import-pick-button">Choisir un fichier</Button></div>
        ) : (
          <div className="text-sm"><p className="mb-3 text-muted-foreground">{data.rows.length} ligne(s) détectée(s). Vérifiez la correspondance des colonnes.</p>
            {data.headers.map((h, i) => (
              <div key={i} className="mb-2 grid grid-cols-[1fr_1fr] items-center gap-3"><div className="truncate"><b>{h || `Colonne ${i + 1}`}</b> <span className="text-xs text-muted-foreground">ex. {data.rows[0][i]}</span></div>
                <select className="h-9 rounded-lg border border-border bg-background px-2 text-sm" value={map[i] || ""} onChange={(e) => setMap({ ...map, [i]: e.target.value })} data-testid={`import-map-${i}`}>
                  <option value="">Ne pas importer</option>{TARGETS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select></div>
            ))}
          </div>
        )}
        <DialogFooter>{data && !res && <Button disabled={busy} onClick={submit} data-testid="import-submit-button">{busy ? "Import en cours…" : `Importer ${data.rows.length} ligne(s)`}</Button>}
          {res && <Button onClick={() => onOpenChange(false)}>Fermer</Button>}</DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export function CategoriesDialog({ open, onOpenChange, categories, onChanged }) {
  const [label, setLabel] = useState("");
  const run = async (fn) => { try { await fn(); onChanged(); } catch (e) { toast.error(errMsg(e)); } };
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[92vh] max-w-md overflow-y-auto" data-testid="categories-dialog">
        <DialogHeader><DialogTitle className="font-display text-2xl font-medium">Métiers</DialogTitle></DialogHeader>
        {categories.map((c) => (
          <div key={c.id} className="flex items-center gap-3" data-testid={`category-row-${c.key}`}>
            <Input defaultValue={c.label} className="h-9" onBlur={(e) => e.target.value.trim() && e.target.value !== c.label && run(() => api.put(`/provider-categories/${c.id}`, { label: e.target.value, active: c.active }))} />
            <label className="flex items-center gap-1.5 whitespace-nowrap text-xs"><input type="checkbox" checked={!!c.is_organizer} onChange={(e) => run(() => api.put(`/provider-categories/${c.id}`, { label: c.label, active: c.active, is_organizer: e.target.checked }))} data-testid={`category-organizer-${c.key}`} />Organisateur</label>
            <Switch checked={c.active} title="Proposé dans les listes" onCheckedChange={(v) => run(() => api.put(`/provider-categories/${c.id}`, { label: c.label, active: v }))} />
          </div>
        ))}
        <div className="flex gap-2 border-t border-border pt-4"><Input value={label} onChange={(e) => setLabel(e.target.value)} placeholder="Nouveau métier" data-testid="category-new-input" />
          <Button disabled={!label.trim()} onClick={() => run(async () => { await api.post("/provider-categories", { label }); setLabel(""); })} data-testid="category-add-button">Ajouter</Button></div>
      </DialogContent>
    </Dialog>
  );
}

const TPL_TYPES = { request: "Demande de disponibilité", reminder: "Relance", confirmation: "Confirmation", filled: "Date pourvue", roadmap: "Feuille de route J-3" };

export function TemplatesDialog({ open, onOpenChange }) {
  const [rows, setRows] = useState([]);
  const [type, setType] = useState("request");
  const [lang, setLang] = useState("fr");
  const [f, setF] = useState({ subject: "", body: "" });
  const load = () => api.get("/message-templates").then((r) => setRows(r.data));
  useEffect(() => { if (open) load(); }, [open]);
  const find = (l) => rows.find((t) => t.type === type && t.language === l && !t.category_key);
  useEffect(() => { const t = rows.find((x) => x.type === type && x.language === lang && !x.category_key); setF({ subject: t?.subject || "", body: t?.body || "" }); }, [rows, type, lang]);
  const save = async () => { try { await api.put("/message-templates", { type, language: lang, category_key: "", ...f }); toast.success("Modèle enregistré"); load(); } catch (e) { toast.error(errMsg(e)); } };
  const sel = "h-9 rounded-lg border border-border bg-background px-2 text-sm";
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[92vh] max-w-2xl overflow-y-auto" data-testid="templates-dialog">
        <DialogHeader><DialogTitle className="font-display text-2xl font-medium">Modèles de message</DialogTitle></DialogHeader>
        <div className="flex flex-wrap items-center gap-2">
          <select className={sel} value={type} onChange={(e) => setType(e.target.value)} data-testid="template-type">{Object.entries(TPL_TYPES).map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select>
          <select className={sel} value={lang} onChange={(e) => setLang(e.target.value)} data-testid="template-language"><option value="fr">🇫🇷 Français</option><option value="en">🇬🇧 English</option></select>
          {lang === "en" && <TranslateButton testid="template-translate" label="Traduire depuis le français (IA)" context="Modèle d'e-mail envoyé à un prestataire." texts={{ subject: find("fr")?.subject || "", body: find("fr")?.body || "" }} onDone={(r) => setF(r)} />}
        </div>
        <Input value={f.subject} onChange={(e) => setF({ ...f, subject: e.target.value })} placeholder="Objet" data-testid="template-subject" />
        <textarea className="min-h-72 w-full rounded-lg border border-border bg-background p-3 text-sm" value={f.body} onChange={(e) => setF({ ...f, body: e.target.value })} data-testid="template-body" />
        <p className="text-xs text-muted-foreground">Les variables entre accolades ({"{prénom}"}, {"{date}"}, {"{lien_reponse}"}…) sont remplacées à l'envoi. La langue utilisée est celle de la fiche du prestataire (anglais pour toute langue autre que le français).</p>
        <DialogFooter><Button disabled={!f.subject || !f.body} onClick={save} data-testid="template-save">Enregistrer</Button></DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

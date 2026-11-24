import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { Plus, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { api, errMsg } from "@/lib/api";

const ko = (e) => toast.error(errMsg(e));
const sel = "h-9 rounded-lg border border-border bg-background px-2 text-sm";
const n3 = (v) => Math.round(v * 1000) / 1000;
export const uomLabel = (u, n = 2) => (!u || u === "piece" ? (n > 1 ? "pièces" : "pièce") : u);
export const dual = (eq, n) => `${n} ${uomLabel(eq?.stock_uom, n)}${eq?.secondary_uom && eq?.qty_per_piece ? ` · ${n3(n * eq.qty_per_piece)} ${eq.secondary_uom}` : ""}`;
const exact = (eq) => eq.rounding === "exact" || !["piece", "lot", "", undefined, null].includes(eq.stock_uom);
export const toPieces = (eq, qty) => { const raw = Number(qty) / (eq.qty_per_piece || 1); return exact(eq) ? n3(raw) : Math.max(1, eq.rounding === "nearest" ? Math.round(raw) : Math.ceil(raw - 1e-9)); };
export const secPrice = (eq) => eq.price_per_secondary ?? (eq.price_day != null && eq.qty_per_piece ? n3(eq.price_day / eq.qty_per_piece) : 0);
export const uomOf = (eq, uom) => (uom === "secondary" && eq?.secondary_uom ? { uom: "secondary", unit: eq.secondary_uom, unit_price: secPrice(eq) } : { uom: "", unit: "", unit_price: eq?.price_day || 0 });
export const matchTemplate = (tpls, eq) => tpls.find((t) => eq.subcategory && t.scopes.includes(eq.subcategory)) || tpls.find((t) => t.scopes.includes(eq.category));
const Lab = ({ label, children }) => <label className="block text-xs text-muted-foreground">{label}<div className="mt-1">{children}</div></label>;

export function UnitsTab({ item, write, onSaved }) {
  const [u, setU] = useState({ uoms: [], stock_uoms: [] });
  const [f, setF] = useState({ stock_uom: item.stock_uom || "piece", secondary_uom: item.secondary_uom || "", qty_per_piece: item.qty_per_piece ?? "", quote_uom: item.quote_uom || "stock", rounding: item.rounding || "ceil", price_day: item.price_day ?? "", price_per_secondary: item.price_per_secondary ?? "" });
  useEffect(() => { api.get("/uoms").then((r) => setU(r.data)).catch(() => {}); }, []);
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value });
  const nn = (v) => (v === "" || v == null ? null : Number(v));
  const qpp = Number(f.qty_per_piece) || 0;
  const save = () => api.put(`/equipment/${item.id}/units`, { ...f, qty_per_piece: nn(f.qty_per_piece), price_day: nn(f.price_day), price_per_secondary: nn(f.price_per_secondary) }).then(() => { toast.success("Unités enregistrées"); onSaved?.(); }).catch(ko);
  const addUom = () => { const code = window.prompt("Nouvelle unité (ex. ml, rouleau)"); if (code?.trim()) api.post("/uoms", { code: code.trim() }).then((r) => setU(r.data)).catch(ko); };
  return (
    <div className="space-y-3 text-sm" data-testid="product-units">
      <div className="rounded-xl bg-secondary p-3 font-semibold" data-testid="units-summary">Stock : {dual({ ...f, qty_per_piece: qpp }, item.qty_total)}</div>
      <div className="grid grid-cols-2 gap-3 md:grid-cols-3">
        <Lab label="Unité de stock *"><select className={`${sel} w-full`} disabled={!write} value={f.stock_uom} onChange={set("stock_uom")} data-testid="units-stock-uom">{u.stock_uoms.map((c) => <option key={c} value={c}>{uomLabel(c, 1)}</option>)}</select></Lab>
        <Lab label="Unité secondaire"><div className="flex gap-1"><select className={`${sel} w-full`} disabled={!write} value={f.secondary_uom} onChange={set("secondary_uom")} data-testid="units-secondary-uom"><option value="">Aucune</option>{u.uoms.filter((x) => x.code !== "piece").map((x) => <option key={x.code} value={x.code}>{x.label}</option>)}</select>{write && <Button type="button" size="sm" variant="ghost" onClick={addUom} title="Ajouter une unité" data-testid="units-add-uom"><Plus /></Button>}</div></Lab>
        <Lab label={`Quantité par pièce${f.secondary_uom ? ` (${f.secondary_uom}) *` : ""}`}><Input type="number" min="0" step="any" disabled={!write || !f.secondary_uom} value={f.qty_per_piece} onChange={set("qty_per_piece")} data-testid="units-qty-per-piece" /></Lab>
        <Lab label="Unité de devis par défaut"><select className={`${sel} w-full`} disabled={!write || !f.secondary_uom} value={f.quote_uom} onChange={set("quote_uom")} data-testid="units-quote-uom"><option value="stock">{uomLabel(f.stock_uom, 1)}</option>{f.secondary_uom && <option value="secondary">{f.secondary_uom}</option>}</select></Lab>
        <Lab label="Arrondi d'une demande en unité secondaire"><select className={`${sel} w-full`} disabled={!write} value={f.rounding} onChange={set("rounding")} data-testid="units-rounding"><option value="ceil">À la pièce supérieure</option><option value="nearest">Au plus proche</option><option value="exact">Exact (pièce partielle)</option></select></Lab>
        <div />
        <Lab label={`Prix / jour HT par ${uomLabel(f.stock_uom, 1)} (€)`}><Input type="number" min="0" step="any" disabled={!write} value={f.price_day} placeholder={f.price_per_secondary !== "" && qpp ? `${n3(f.price_per_secondary * qpp)} (calculé)` : "à définir"} onChange={set("price_day")} data-testid="units-price-stock" /></Lab>
        <Lab label={`Prix / jour HT par ${f.secondary_uom || "unité secondaire"} (€)`}><Input type="number" min="0" step="any" disabled={!write || !f.secondary_uom} value={f.price_per_secondary} placeholder={f.price_day !== "" && qpp ? `${n3(f.price_day / qpp)} (calculé)` : ""} onChange={set("price_per_secondary")} data-testid="units-price-secondary" /></Lab>
      </div>
      {write && <Button size="sm" onClick={save} data-testid="units-save">Enregistrer les unités</Button>}
    </div>
  );
}

export function AttrsTab({ item, write, onSaved }) {
  const [tpl, setTpl] = useState(null);
  const [v, setV] = useState(item.attributes || {});
  const [extra, setExtra] = useState(item.extra_attributes || []);
  useEffect(() => { api.get("/attribute-templates").then((r) => setTpl(matchTemplate(r.data, item) || { name: "", fields: [] })).catch(ko); }, [item]);
  if (!tpl) return null;
  const set = (k, val) => setV({ ...v, [k]: val });
  const save = () => api.put(`/equipment/${item.id}/attributes`, { attributes: v, extra_attributes: extra.filter((e) => e.label.trim()) }).then((r) => { setV(r.data.attributes); toast.success("Caractéristiques enregistrées"); onSaved?.(); }).catch(ko);
  return (
    <div className="space-y-3 text-sm" data-testid="product-attrs">
      <p className="text-xs text-muted-foreground" data-testid="attrs-template-name">{tpl.name ? `Modèle : ${tpl.name}` : "Aucun modèle pour cette famille : ajoutez des champs libres, ou créez un modèle (Catalogue › Modèles de caractéristiques)."}</p>
      {item.specs && <p className="rounded-lg bg-secondary p-2 text-xs">Texte importé d'Odoo : {item.specs}</p>}
      <div className="grid grid-cols-2 gap-3 md:grid-cols-3">{tpl.fields.map((fd) => (
        <Lab key={fd.code} label={`${fd.label}${fd.unit ? ` (${fd.unit})` : ""}`}>
          {fd.type === "bool" ? <select className={`${sel} w-full`} disabled={!write} value={v[fd.code] == null ? "" : v[fd.code] ? "1" : "0"} onChange={(e) => set(fd.code, e.target.value === "" ? null : e.target.value === "1")} data-testid={`attr-${fd.code}`}><option value="">—</option><option value="1">Oui</option><option value="0">Non</option></select>
            : fd.type === "select" ? <select className={`${sel} w-full`} disabled={!write} value={v[fd.code] ?? ""} onChange={(e) => set(fd.code, e.target.value)} data-testid={`attr-${fd.code}`}><option value="">—</option>{fd.options.map((o) => <option key={o}>{o}</option>)}</select>
              : <Input type={fd.type === "number" ? "number" : "text"} step="any" disabled={!write} value={v[fd.code] ?? ""} onChange={(e) => set(fd.code, e.target.value)} data-testid={`attr-${fd.code}`} />}
        </Lab>))}</div>
      {extra.map((e, i) => <div key={i} className="flex gap-2" data-testid={`attr-extra-${i}`}><Input className="h-9" placeholder="Champ libre" disabled={!write} value={e.label} onChange={(x) => setExtra(extra.map((y, j) => (j === i ? { ...y, label: x.target.value } : y)))} /><Input className="h-9" placeholder="Valeur" disabled={!write} value={e.value} onChange={(x) => setExtra(extra.map((y, j) => (j === i ? { ...y, value: x.target.value } : y)))} /><Input className="h-9 w-24" placeholder="Unité" disabled={!write} value={e.unit || ""} onChange={(x) => setExtra(extra.map((y, j) => (j === i ? { ...y, unit: x.target.value } : y)))} />{write && <button aria-label="Supprimer" onClick={() => setExtra(extra.filter((_, j) => j !== i))}><Trash2 className="h-4 w-4" /></button>}</div>)}
      {write && <div className="flex gap-2"><Button size="sm" variant="outline" onClick={() => setExtra([...extra, { label: "", value: "", unit: "" }])} data-testid="attr-add-extra"><Plus />Champ libre</Button><Button size="sm" className="ml-auto" onClick={save} data-testid="attrs-save">Enregistrer les caractéristiques</Button></div>}
    </div>
  );
}

export function TemplatesDialog({ open, onOpenChange, onSaved }) {
  const [list, setList] = useState([]);
  const [t, setT] = useState(null);
  const load = useCallback(() => api.get("/attribute-templates").then((r) => setList(r.data)).catch(ko), []);
  useEffect(() => { if (open) { load(); setT(null); } }, [open, load]);
  const up = (i, k, val) => setT({ ...t, fields: t.fields.map((x, j) => (j === i ? { ...x, [k]: val } : x)) });
  const save = () => api.put(`/attribute-templates/${t.id}`, { name: t.name, scopes: t.scopes, fields: t.fields.filter((x) => x.label.trim()) }).then((r) => { setList(r.data); setT(null); toast.success("Modèle enregistré : ses champs apparaissent sur tous les produits de la famille"); onSaved?.(); }).catch(ko);
  return (
    <Dialog open={open} onOpenChange={onOpenChange}><DialogContent className="max-h-[92vh] max-w-4xl overflow-y-auto" data-testid="templates-dialog">
      <DialogHeader><DialogTitle>Modèles de caractéristiques</DialogTitle><DialogDescription>Un modèle s'applique aux produits dont la catégorie ou la sous-catégorie figure dans ses familles.</DialogDescription></DialogHeader>
      {!t ? <div className="space-y-2 text-sm">{list.map((x) => <div key={x.id} className="flex flex-wrap items-center gap-2 rounded-xl border border-border p-3" data-testid={`template-${x.id}`}><b>{x.name}</b><span className="text-xs text-muted-foreground">{x.scopes.join(", ")} · {x.fields.length} champs{x.custom ? " · personnalisé" : ""}</span><span className="flex-1" />
        {x.custom && <button className="text-xs underline" onClick={() => window.confirm("Revenir au modèle par défaut (ou supprimer ce modèle personnel) ?") && api.delete(`/attribute-templates/${x.id}`).then((r) => { setList(r.data); onSaved?.(); }).catch(ko)} data-testid={`template-reset-${x.id}`}>Réinitialiser</button>}
        <Button size="sm" variant="outline" onClick={() => setT({ ...x, fields: x.fields.map((y) => ({ ...y })) })} data-testid={`template-edit-${x.id}`}>Modifier</Button></div>)}
        <Button size="sm" onClick={() => setT({ id: "new", name: "", scopes: [], fields: [] })} data-testid="template-new"><Plus />Nouveau modèle</Button></div>
        : <div className="space-y-2 text-sm">
          <div className="grid grid-cols-2 gap-2"><Input placeholder="Nom du modèle *" value={t.name} onChange={(e) => setT({ ...t, name: e.target.value })} data-testid="template-name" /><Input placeholder="Familles (catégories ou sous-catégories, séparées par des virgules)" value={t.scopes.join(", ")} onChange={(e) => setT({ ...t, scopes: e.target.value.split(",").map((x) => x.trimStart()) })} data-testid="template-scopes" /></div>
          {t.fields.map((x, i) => <div key={i} className="grid grid-cols-12 gap-2" data-testid={`template-field-${i}`}><Input className="col-span-4 h-9" placeholder="Libellé" value={x.label} onChange={(e) => up(i, "label", e.target.value)} data-testid={`template-field-label-${i}`} />
            <select className={`${sel} col-span-2`} value={x.type} onChange={(e) => up(i, "type", e.target.value)}><option value="number">Nombre</option><option value="text">Texte</option><option value="select">Liste</option><option value="bool">Oui / non</option></select>
            <Input className="col-span-2 h-9" placeholder="Unité" value={x.unit || ""} onChange={(e) => up(i, "unit", e.target.value)} /><Input className="col-span-3 h-9" placeholder="Choix (liste), séparés par des virgules" disabled={x.type !== "select"} value={(x.options || []).join(", ")} onChange={(e) => up(i, "options", e.target.value.split(",").map((y) => y.trim()).filter(Boolean))} />
            <button className="col-span-1" aria-label="Supprimer" onClick={() => setT({ ...t, fields: t.fields.filter((_, j) => j !== i) })}><Trash2 className="h-4 w-4" /></button></div>)}
          <div className="flex gap-2"><Button size="sm" variant="outline" onClick={() => setT({ ...t, fields: [...t.fields, { code: "", label: "", type: "text", unit: "", options: [] }] })} data-testid="template-add-field"><Plus />Champ</Button><span className="flex-1" /><Button size="sm" variant="ghost" onClick={() => setT(null)}>Annuler</Button><Button size="sm" disabled={!t.name.trim()} onClick={save} data-testid="template-save">Enregistrer le modèle</Button></div>
        </div>}
    </DialogContent></Dialog>
  );
}

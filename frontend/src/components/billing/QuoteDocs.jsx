import { useEffect, useState } from "react";
import axios from "axios";
import { toast } from "sonner";
import { Plus, Trash2, ArrowUp, ArrowDown, Languages, Copy, Layers, Users, History, Pencil } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog";
import { Field, Section, Loading } from "@/components/common";
import { api, errMsg } from "@/lib/api";
import { fmtEur2 } from "@/lib/constants";
import { FileImg, UploadButton } from "@/lib/files";

const BASE = process.env.REACT_APP_BACKEND_URL;
const ko = (e) => toast.error(errMsg(e));
const uid = () => (crypto.randomUUID ? crypto.randomUUID() : String(Math.random()).slice(2));
const sel = "h-9 rounded-lg border border-border bg-background px-2 text-xs";
const TYPES = [["title", "Titre"], ["text", "Texte"], ["image", "Image"], ["columns", "2 colonnes"], ["quote", "Citation / avis"], ["schedule", "Échéancier (acompte / solde)"]];
const swap = (a, i, d) => { const j = i + d; if (j < 0 || j >= a.length) return a; const n = [...a]; [n[i], n[j]] = [n[j], n[i]]; return n; };

const inline = (s) => s.split(/(\*\*.+?\*\*|\*.+?\*)/g).map((p, i) => (p.startsWith("**") ? <b key={i}>{p.slice(2, -2)}</b> : p.startsWith("*") && p.length > 2 ? <i key={i}>{p.slice(1, -1)}</i> : p));
const Rich = ({ text }) => <div>{(text || "").split("\n").map((l, i) => (l.startsWith("- ") ? <div key={i} className="pl-4">• {inline(l.slice(2))}</div> : <div key={i} className="min-h-[1em]">{inline(l)}</div>))}</div>;

export function PublicPages({ pages, brand }) {
  if (!pages?.length) return null;
  const src = (u) => (u?.startsWith("/") ? BASE + u : u);
  return pages.map((p, i) => (
    <div key={i} className={`card-soft mt-4 space-y-4 p-6 ${brand?.font === "serif" ? "font-serif" : ""}`} data-testid="public-page">
      {p.blocks.map((b) => b.type === "title" ? <h2 key={b.id} className="text-2xl font-bold" style={{ color: brand?.color }}><Rich text={b.text} /></h2>
        : b.type === "text" ? <div key={b.id} className="text-sm"><Rich text={b.text} /></div>
          : b.type === "image" ? (b.image ? <img key={b.id} src={src(b.image)} alt="" className={`w-full rounded-xl object-cover ${b.mode === "full" ? "" : "max-h-64"}`} /> : null)
            : b.type === "columns" ? <div key={b.id} className="grid grid-cols-1 gap-4 text-sm sm:grid-cols-2"><Rich text={b.text} /><Rich text={b.right} /></div>
              : b.type === "quote" ? <blockquote key={b.id} className="border-l-2 border-border pl-4 text-sm italic"><Rich text={`« ${b.text} »`} />{b.right && <div className="mt-1 not-italic text-muted-foreground">— {b.right}</div>}</blockquote>
                : <div key={b.id} className="divide-y divide-border text-sm" data-testid="public-schedule">{(b.rows || []).map((r) => <div key={r[0]} className="flex justify-between py-2"><span>{r[0]}</span><b>{r[1]}</b></div>)}</div>)}
    </div>
  ));
}

export function BlocksEditor({ blocks, onChange, fields = [], testid = "blocks" }) {
  const up = (i, patch) => onChange(blocks.map((b, j) => (j === i ? { ...b, ...patch } : b)));
  return (
    <div className="space-y-2" data-testid={testid}>
      {blocks.map((b, i) => (
        <div key={b.id} className="rounded-xl border border-border p-2" data-testid={`${testid}-block-${i}`}>
          <div className="mb-1.5 flex items-center gap-1.5">
            <select className={sel} value={b.type} onChange={(e) => up(i, { type: e.target.value })} aria-label="Type de bloc">{TYPES.map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select>
            {b.type === "image" && <select className={sel} value={b.mode} onChange={(e) => up(i, { mode: e.target.value })} aria-label="Format"><option value="banner">Bandeau</option><option value="full">Pleine page</option></select>}
            <span className="ml-auto" />
            <button type="button" className="icon-btn" onClick={() => onChange(swap(blocks, i, -1))} aria-label="Monter"><ArrowUp className="h-3.5 w-3.5" /></button>
            <button type="button" className="icon-btn" onClick={() => onChange(swap(blocks, i, 1))} aria-label="Descendre"><ArrowDown className="h-3.5 w-3.5" /></button>
            <button type="button" className="icon-btn" onClick={() => onChange(blocks.filter((_, j) => j !== i))} aria-label="Supprimer"><Trash2 className="h-3.5 w-3.5" /></button>
          </div>
          {b.type === "title" && <Input value={b.text} onChange={(e) => up(i, { text: e.target.value })} placeholder="Titre" data-testid={`${testid}-text-${i}`} />}
          {["text", "quote"].includes(b.type) && <Textarea rows={3} value={b.text} onChange={(e) => up(i, { text: e.target.value })} placeholder="Texte (**gras**, *italique*, - liste)" data-testid={`${testid}-text-${i}`} />}
          {b.type === "quote" && <Input className="mt-1.5" value={b.right} onChange={(e) => up(i, { right: e.target.value })} placeholder="Auteur" />}
          {b.type === "columns" && <div className="grid grid-cols-2 gap-1.5"><Textarea rows={3} value={b.text} onChange={(e) => up(i, { text: e.target.value })} placeholder="Colonne gauche" /><Textarea rows={3} value={b.right} onChange={(e) => up(i, { right: e.target.value })} placeholder="Colonne droite" /></div>}
          {b.type === "image" && <div className="flex items-center gap-2">{b.image && <FileImg src={b.image} className="h-14 w-24 rounded-lg object-cover" />}<UploadButton accept="image/*" multiple={false} label="Image" onUploaded={(r) => up(i, { image: r[0] })} /></div>}
          {b.type === "schedule" && <p className="text-xs text-muted-foreground">Acompte, solde et total TTC calculés depuis le devis.</p>}
        </div>
      ))}
      <div className="flex flex-wrap items-center gap-2">
        <Button type="button" size="sm" variant="outline" onClick={() => onChange([...blocks, { id: uid(), type: "text", text: "", right: "", image: "", mode: "banner" }])} data-testid={`${testid}-add`}><Plus />Bloc</Button>
        {fields.length > 0 && <span className="text-[11px] text-muted-foreground">Champs : {fields.map((f) => `{${f}}`).join(" ")}</span>}
      </div>
    </div>
  );
}

function TranslateBlocks({ blocks, onDone }) {
  const [busy, setBusy] = useState(false);
  const run = async () => {
    setBusy(true);
    try {
      const all = blocks.flatMap((b) => [[b.id, b.text], [`${b.id}|r`, b.right]]).filter(([, v]) => v?.trim());
      const out = {};
      for (let i = 0; i < all.length; i += 12) Object.assign(out, (await api.post("/translate", { texts: Object.fromEntries(all.slice(i, i + 12)), target: "en", context: "Page d'un devis." })).data);
      onDone(blocks.map((b) => ({ ...b, id: uid(), text: out[b.id] ?? b.text, right: out[`${b.id}|r`] ?? b.right })));
      toast.success("Traduction générée : relisez-la avant d'enregistrer");
    } catch (e) { ko(e); }
    setBusy(false);
  };
  return <Button type="button" size="sm" variant="outline" disabled={busy} onClick={run} data-testid="page-translate"><Languages />{busy ? "Traduction…" : "Traduire (IA)"}</Button>;
}

const NEW_BRAND = { name: "", logo: "", color: "#171717", font: "sans", legal_name: "", siret: "", vat_number: "", legal_mentions: "", legal_mentions_en: "", terms: "", terms_en: "", is_default: false };
const NEW_PAGE = { name: "", kind: "header", brand_id: "", blocks_fr: [], blocks_en: [], default_on: true, order: 0 };

export function DocumentTemplates({ write }) {
  const [d, setD] = useState(null);
  const [brands, setBrands] = useState([]);
  const [page, setPage] = useState(null);
  const [brand, setBrand] = useState(null);
  const [lang, setLang] = useState("fr");
  const load = () => Promise.all([api.get("/document-pages"), api.get("/brand-templates")]).then(([p, b]) => { setD(p.data); setBrands(b.data); }).catch(ko);
  useEffect(() => { load(); }, []);
  if (!d) return <Loading />;
  const save = async (path, obj, close) => { try { const { id, org_id, created_at, updated_at, ...body } = obj; await (id ? api.put(`${path}/${id}`, body) : api.post(path, body)); toast.success("Enregistré"); close(null); load(); } catch (e) { ko(e); } };
  const del = async (path, id) => { if (!window.confirm("Supprimer ?")) return; try { await api.delete(`${path}/${id}`); load(); } catch (e) { ko(e); } };
  const k = lang === "fr" ? "blocks_fr" : "blocks_en";
  return (
    <div className="space-y-6" data-testid="document-templates">
      <Section title="Gabarits de marque" actions={write && <Button size="sm" onClick={() => setBrand(NEW_BRAND)} data-testid="brand-new"><Plus />Gabarit</Button>}>
        <div className="divide-y divide-border">{brands.map((b) => (
          <div key={b.id} className="flex items-center gap-3 py-2.5 text-sm" data-testid={`brand-row-${b.id}`}>
            <span className="h-5 w-5 rounded-full border border-border" style={{ background: b.color }} /><span className="font-semibold">{b.name}</span>{b.is_default && <span className="rounded-full bg-secondary px-2 py-0.5 text-[11px]">Par défaut</span>}
            <span className="ml-auto" />{write && <><button className="icon-btn" onClick={() => setBrand(b)} aria-label="Modifier"><Pencil className="h-3.5 w-3.5" /></button>{!b.is_default && <button className="icon-btn" onClick={() => del("/brand-templates", b.id)} aria-label="Supprimer"><Trash2 className="h-3.5 w-3.5" /></button>}</>}
          </div>))}</div>
      </Section>
      <Section title="Pages d'en-tête et de clôture" actions={write && <Button size="sm" onClick={() => { setLang("fr"); setPage(NEW_PAGE); }} data-testid="page-new"><Plus />Page</Button>}>
        <div className="divide-y divide-border">{d.pages.map((p) => (
          <div key={p.id} className="flex items-center gap-3 py-2.5 text-sm" data-testid={`page-row-${p.id}`}>
            <span className="rounded-full bg-secondary px-2 py-0.5 text-[11px]">{p.kind === "header" ? "En-tête" : "Clôture"}</span><span className="font-semibold">{p.name}</span>
            <span className="text-xs text-muted-foreground">{p.default_on ? "incluse par défaut" : "à cocher"}{p.blocks_en?.length ? " · FR / EN" : " · FR"}{p.brand_id ? ` · ${brands.find((b) => b.id === p.brand_id)?.name || ""}` : ""}</span>
            <span className="ml-auto" />{write && <><button className="icon-btn" onClick={() => { setLang("fr"); setPage(p); }} aria-label="Modifier" data-testid={`page-edit-${p.id}`}><Pencil className="h-3.5 w-3.5" /></button><button className="icon-btn" onClick={() => del("/document-pages", p.id)} aria-label="Supprimer"><Trash2 className="h-3.5 w-3.5" /></button></>}
          </div>))}</div>
      </Section>
      {page && (
        <Dialog open onOpenChange={() => setPage(null)}>
          <DialogContent className="max-h-[92vh] max-w-3xl overflow-y-auto">
            <DialogHeader><DialogTitle className="text-xl font-bold">{page.id ? "Modifier la page" : "Nouvelle page"}</DialogTitle></DialogHeader>
            <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
              <Field label="Nom" className="col-span-2"><Input value={page.name} onChange={(e) => setPage({ ...page, name: e.target.value })} data-testid="page-name" /></Field>
              <Field label="Position"><select className={`${sel} w-full`} value={page.kind} onChange={(e) => setPage({ ...page, kind: e.target.value })} data-testid="page-kind"><option value="header">En-tête</option><option value="closing">Clôture</option></select></Field>
              <Field label="Marque"><select className={`${sel} w-full`} value={page.brand_id} onChange={(e) => setPage({ ...page, brand_id: e.target.value })}><option value="">Toutes</option>{brands.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}</select></Field>
              <label className="col-span-2 flex items-center gap-2 text-sm"><input type="checkbox" checked={page.default_on} onChange={(e) => setPage({ ...page, default_on: e.target.checked })} data-testid="page-default-on" />Incluse par défaut dans les devis</label>
              <Field label="Ordre"><Input type="number" value={page.order} onChange={(e) => setPage({ ...page, order: Number(e.target.value) || 0 })} /></Field>
            </div>
            <div className="flex items-center gap-2">
              {["fr", "en"].map((l) => <button key={l} type="button" onClick={() => setLang(l)} data-testid={`page-lang-${l}`} className={`rounded-full px-3 py-1 text-xs font-semibold uppercase ${lang === l ? "bg-foreground text-background" : "text-muted-foreground"}`}>{l}</button>)}
              {lang === "en" && <TranslateBlocks blocks={page.blocks_fr} onDone={(blocks_en) => setPage({ ...page, blocks_en })} />}
              {lang === "en" && !page.blocks_en.length && <span className="text-xs text-muted-foreground">Vide : la version française sera utilisée.</span>}
            </div>
            <BlocksEditor blocks={page[k]} onChange={(b) => setPage({ ...page, [k]: b })} fields={d.fields} testid="page-blocks" />
            <DialogFooter><Button onClick={() => save("/document-pages", page, setPage)} data-testid="page-save">Enregistrer</Button></DialogFooter>
          </DialogContent>
        </Dialog>
      )}
      {brand && (
        <Dialog open onOpenChange={() => setBrand(null)}>
          <DialogContent className="max-h-[92vh] max-w-2xl overflow-y-auto">
            <DialogHeader><DialogTitle className="text-xl font-bold">{brand.id ? "Modifier le gabarit" : "Nouveau gabarit de marque"}</DialogTitle></DialogHeader>
            <div className="grid grid-cols-2 gap-3">
              <Field label="Nom de la marque"><Input value={brand.name} onChange={(e) => setBrand({ ...brand, name: e.target.value })} data-testid="brand-name" /></Field>
              <Field label="Couleur"><Input type="color" value={brand.color} onChange={(e) => setBrand({ ...brand, color: e.target.value })} data-testid="brand-color" /></Field>
              <Field label="Typographie"><select className={`${sel} w-full`} value={brand.font} onChange={(e) => setBrand({ ...brand, font: e.target.value })}><option value="sans">Sans empattement</option><option value="serif">Avec empattement</option></select></Field>
              <Field label="Logo"><div className="flex items-center gap-2">{brand.logo && <FileImg src={brand.logo} className="h-9 w-16 rounded object-contain" />}<UploadButton accept="image/*" multiple={false} label="Logo" onUploaded={(r) => setBrand({ ...brand, logo: r[0] })} /></div></Field>
              {[["legal_name", "Raison sociale"], ["siret", "SIRET"], ["vat_number", "N° TVA"]].map(([f, l]) => <Field key={f} label={l}><Input value={brand[f]} onChange={(e) => setBrand({ ...brand, [f]: e.target.value })} /></Field>)}
              <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={brand.is_default} onChange={(e) => setBrand({ ...brand, is_default: e.target.checked })} />Gabarit par défaut</label>
              {[["legal_mentions", "Mentions légales (pied de page)"], ["legal_mentions_en", "Legal mentions (EN)"], ["terms", "CGV"], ["terms_en", "Terms (EN)"]].map(([f, l]) => <Field key={f} label={l} className="col-span-2"><Textarea rows={3} value={brand[f]} onChange={(e) => setBrand({ ...brand, [f]: e.target.value })} /></Field>)}
            </div>
            <p className="text-xs text-muted-foreground">Champs vides : ceux de l'organisation sont utilisés.</p>
            <DialogFooter><Button onClick={() => save("/brand-templates", brand, setBrand)} data-testid="brand-save">Enregistrer</Button></DialogFooter>
          </DialogContent>
        </Dialog>
      )}
    </div>
  );
}

function PagesDialog({ q, onClose }) {
  const [d, setD] = useState(null);
  const [edit, setEdit] = useState(null);
  useEffect(() => { api.get(`/quotes/${q.id}/pages`).then((r) => setD(r.data)).catch(ko); }, [q.id]);
  if (!d) return null;
  const save = async () => { const strip = (a) => a.map(({ template_id, enabled, override }) => ({ template_id, enabled, override })); try { await api.put(`/quotes/${q.id}/pages`, { brand_template_id: d.brand_template_id, header: strip(d.header), closing: strip(d.closing) }); toast.success("Pages enregistrées"); onClose(); } catch (e) { ko(e); } };
  const list = (kind, label) => (
    <div data-testid={`quote-pages-${kind}`}>
      <div className="mb-1.5 text-sm font-semibold">{label}</div>
      {!d[kind].length && <p className="text-xs text-muted-foreground">Aucune page : créez-en dans Entreprise &gt; Modèles de documents.</p>}
      {d[kind].map((p, i) => {
        const up = (patch) => setD({ ...d, [kind]: d[kind].map((x, j) => (j === i ? { ...x, ...patch } : x)) });
        const open = edit === `${kind}${i}`;
        return (
          <div key={p.template_id} className="mb-1.5 rounded-xl border border-border p-2">
            <div className="flex items-center gap-2 text-sm">
              <input type="checkbox" checked={p.enabled} onChange={(e) => up({ enabled: e.target.checked })} aria-label={p.name} data-testid={`quote-page-toggle-${p.template_id}`} /><span className="font-medium">{p.name}</span>{p.override && <span className="rounded-full bg-amber-500/10 px-2 py-0.5 text-[11px] text-amber-600">modifiée pour ce devis</span>}
              <span className="ml-auto" />
              <button type="button" className="icon-btn" onClick={() => setD({ ...d, [kind]: swap(d[kind], i, -1) })} aria-label="Monter"><ArrowUp className="h-3.5 w-3.5" /></button><button type="button" className="icon-btn" onClick={() => setD({ ...d, [kind]: swap(d[kind], i, 1) })} aria-label="Descendre"><ArrowDown className="h-3.5 w-3.5" /></button>
              <Button type="button" size="sm" variant="ghost" onClick={() => { if (!p.override) up({ override: p.blocks.map((b) => ({ ...b })) }); setEdit(open ? null : `${kind}${i}`); }} data-testid={`quote-page-edit-${p.template_id}`}>{open ? "Fermer" : "Modifier pour ce devis"}</Button>
              {p.override && <Button type="button" size="sm" variant="ghost" onClick={() => { up({ override: null }); setEdit(null); }}>Revenir au modèle</Button>}
            </div>
            {open && p.override && <div className="mt-2"><BlocksEditor blocks={p.override} onChange={(override) => up({ override })} fields={d.fields} testid="quote-page-blocks" /></div>}
          </div>
        );
      })}
    </div>
  );
  return (
    <Dialog open onOpenChange={onClose}>
      <DialogContent className="max-h-[92vh] max-w-3xl overflow-y-auto">
        <DialogHeader><DialogTitle className="text-xl font-bold">Pages du devis {q.number}</DialogTitle></DialogHeader>
        <Field label="Gabarit de marque"><select className={`${sel} w-full`} value={d.brand_template_id} onChange={(e) => setD({ ...d, brand_template_id: e.target.value })} data-testid="quote-brand-select">{d.brands.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}</select></Field>
        <p className="text-xs text-muted-foreground">Langue du devis : {d.language}</p>
        {list("header", "Pages d'en-tête")}{list("closing", "Pages de clôture")}
        <DialogFooter><Button onClick={save} data-testid="quote-pages-save">Enregistrer</Button></DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

const KINDS = { organizer: "Organisateur / wedding planner", venue: "Lieu / technique (sans prix)", provider: "Prestataire (sans prix)" };

function ViewsDialog({ q, onClose }) {
  const [d, setD] = useState(null);
  const [f, setF] = useState({ kind: "venue", label: "", section_ids: [], price_display: "same" });
  const load = () => api.get(`/quotes/${q.id}/views`).then((r) => setD(r.data)).catch(ko);
  useEffect(() => { load(); }, [q.id]); // eslint-disable-line react-hooks/exhaustive-deps
  if (!d) return null;
  const copy = (path) => { const url = `${window.location.origin}${path}`; navigator.clipboard?.writeText(url).catch(() => {}); toast.success("Lien copié"); window.open(`${url}?apercu=1`, "_blank", "noopener"); };
  const add = async () => { try { await api.post(`/quotes/${q.id}/views`, f); setF({ ...f, label: "", section_ids: [] }); load(); } catch (e) { ko(e); } };
  return (
    <Dialog open onOpenChange={onClose}>
      <DialogContent className="max-h-[92vh] max-w-2xl overflow-y-auto">
        <DialogHeader><DialogTitle className="text-xl font-bold">Versions destinataires — {q.number}</DialogTitle></DialogHeader>
        <div className="divide-y divide-border text-sm" data-testid="quote-views">
          <div className="flex items-center gap-2 py-2"><span className="font-semibold">Client</span><span className="text-xs text-muted-foreground">contractuelle, signable</span><span className="ml-auto" /><Button size="sm" variant="outline" onClick={() => copy(`/devis/${d.client_token}`)}><Copy />Lien</Button>{d.can_renew && <Button size="sm" variant="ghost" onClick={() => window.confirm("L'ancien lien ne fonctionnera plus. Continuer ?") && api.post(`/quotes/${q.id}/share/revoke`).then((r) => { load(); copy(`/devis/${r.data.token}`); }).catch(ko)} data-testid="quote-link-renew">Renvoyer un nouveau lien</Button>}</div>
          {d.views.map((v) => (
            <div key={v.id} className="flex items-center gap-2 py-2" data-testid={`quote-view-${v.id}`}><span className="font-semibold">{v.label || KINDS[v.kind]}</span><span className="text-xs text-muted-foreground">{v.price_display === "none" ? "sans prix" : v.price_display === "same" ? "prix comme le client" : v.price_display}{v.section_ids.length ? ` · ${v.section_ids.length} section(s)` : ""}</span>
              <span className="ml-auto" /><Button size="sm" variant="outline" onClick={() => copy(`/devis/v/${v.token}`)} data-testid={`quote-view-link-${v.id}`}><Copy />Lien</Button><button className="icon-btn" onClick={() => api.delete(`/quote-views/${v.id}`).then(load).catch(ko)} aria-label="Supprimer"><Trash2 className="h-3.5 w-3.5" /></button></div>
          ))}
        </div>
        <div className="space-y-2 rounded-2xl border border-border p-3">
          <div className="text-sm font-semibold">Nouvelle version</div>
          <div className="grid grid-cols-2 gap-2">
            <select className={sel} value={f.kind} onChange={(e) => setF({ ...f, kind: e.target.value })} data-testid="view-kind">{Object.entries(KINDS).map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select>
            <Input className="h-9" placeholder="Libellé (ex. DJ Marc)" value={f.label} onChange={(e) => setF({ ...f, label: e.target.value })} data-testid="view-label" />
            {f.kind === "organizer" && <select className={sel} value={f.price_display} onChange={(e) => setF({ ...f, price_display: e.target.value })} data-testid="view-price"><option value="same">Prix comme le client</option><option value="section_totals">Total par section</option><option value="total_only">Total global seul</option><option value="none">Sans prix</option></select>}
          </div>
          <div className="flex flex-wrap gap-3 text-xs">{d.sections.map((s) => <label key={s.id} className="flex items-center gap-1"><input type="checkbox" checked={f.section_ids.includes(s.id)} onChange={(e) => setF({ ...f, section_ids: e.target.checked ? [...f.section_ids, s.id] : f.section_ids.filter((x) => x !== s.id) })} />{s.title}</label>)}<span className="text-muted-foreground">(aucune cochée = toutes)</span></div>
          <Button size="sm" onClick={add} data-testid="view-add"><Plus />Créer la version</Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}

function VersionsDialog({ q, onClose }) {
  const [rows, setRows] = useState(null);
  const [cmp, setCmp] = useState(null);
  useEffect(() => { api.get(`/quotes/${q.id}/versions`).then((r) => setRows(r.data)).catch(ko); }, [q.id]);
  if (!rows) return null;
  const line = (x) => `${x.qty} × ${x.label} — ${fmtEur2(x.unit_price)}`;
  return (
    <Dialog open onOpenChange={onClose}>
      <DialogContent className="max-h-[92vh] max-w-2xl overflow-y-auto">
        <DialogHeader><DialogTitle className="text-xl font-bold">Versions du devis {q.number}</DialogTitle></DialogHeader>
        <div className="divide-y divide-border text-sm" data-testid="quote-versions">
          {rows.map((r) => (
            <div key={r.id} className="flex items-center gap-2 py-2" data-testid={`quote-version-${r.version}`}><span className="font-semibold">V{r.version}</span><span className="text-xs text-muted-foreground">{r.active ? "active" : "ancienne version"}{r.signed ? " · signée" : ""} · {fmtEur2(r.total_ttc)} TTC</span>
              <span className="ml-auto" />{r.share_token && <Button size="sm" variant="ghost" onClick={() => window.open(`/devis/${r.share_token}?apercu=1`, "_blank", "noopener")}>Voir</Button>}
              {r.id !== q.id && <Button size="sm" variant="outline" onClick={() => api.get(`/quotes/${q.id}/compare`, { params: { other: r.id } }).then((x) => setCmp(x.data)).catch(ko)} data-testid={`quote-compare-${r.version}`}>Comparer</Button>}</div>
          ))}
        </div>
        {cmp && (
          <div className="space-y-2 rounded-2xl border border-border p-3 text-sm" data-testid="quote-compare">
            <div className="font-semibold">V{cmp.from.version} → V{cmp.to.version} : {fmtEur2(cmp.from.total_ttc)} → {fmtEur2(cmp.to.total_ttc)} TTC ({cmp.diff_ttc >= 0 ? "+" : ""}{fmtEur2(cmp.diff_ttc)})</div>
            {cmp.added.map((x, i) => <div key={`a${i}`} className="text-emerald-600">+ {line(x)}</div>)}
            {cmp.removed.map((x, i) => <div key={`r${i}`} className="text-red-600">− {line(x)}</div>)}
            {cmp.changed.map((x, i) => <div key={`c${i}`} className="text-amber-600">~ {line(x.before)} → {line(x.after)}</div>)}
            {!cmp.added.length && !cmp.removed.length && !cmp.changed.length && <div className="text-muted-foreground">Aucune différence sur les lignes.</div>}
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}

export function QuoteDocsButtons({ q, canQuote, onChanged }) {
  const [open, setOpen] = useState("");
  const open_ = ["brouillon", "envoye", "vu", "negociation"].includes(q.status);
  const locked = q.active !== false && (q.signature?.status === "done" || ["accepte", "refuse", "expire"].includes(q.status));
  const v2 = async () => { if (!window.confirm("Créer une nouvelle version ? La version actuelle restera consultable, non signable.")) return; try { const r = await api.post(`/quotes/${q.id}/new-version`); toast.success(`Version V${r.data.version} créée en brouillon`); onChanged(); } catch (e) { ko(e); } };
  return (
    <>
      {canQuote && open_ && <Button size="sm" variant="outline" onClick={() => setOpen("pages")} data-testid={`quote-pages-${q.number}`}><Layers />Pages</Button>}
      <Button size="sm" variant="outline" onClick={() => setOpen("views")} data-testid={`quote-views-${q.number}`}><Users />Versions destinataires</Button>
      <Button size="sm" variant="outline" onClick={() => setOpen("versions")} data-testid={`quote-versions-${q.number}`}><History />V{q.version || 1}</Button>
      {canQuote && locked && <Button size="sm" onClick={v2} data-testid={`quote-new-version-${q.number}`}><Plus />Nouvelle version</Button>}
      {open === "pages" && <PagesDialog q={q} onClose={() => setOpen("")} />}
      {open === "views" && <ViewsDialog q={q} onClose={() => setOpen("")} />}
      {open === "versions" && <VersionsDialog q={q} onClose={() => setOpen("")} />}
    </>
  );
}

const ST = {
  fr: { accept: "Bon pour accord", name: "Nom et prénom du signataire", title: "Qualité (facultatif)", get: "Recevoir mon code par e-mail", code: "Code reçu par e-mail (6 chiffres)", sign: "Accepter et signer", sent: "Code envoyé à", signed: "Devis signé", by: "par", refuse: "Refuser le devis", reason: "Motif (facultatif)", confirmRefuse: "Confirmer le refus", simple: "Signature électronique simple (code envoyé par e-mail).", yousign: "Une demande de signature vous a été envoyée par e-mail.", old: "Cette version a été remplacée : elle n'est plus signable.", err: "Une erreur est survenue" },
  en: { accept: "Approved", name: "Signatory's full name", title: "Position (optional)", get: "Email me my code", code: "Code received by email (6 digits)", sign: "Accept and sign", sent: "Code sent to", signed: "Quote signed", by: "by", refuse: "Decline the quote", reason: "Reason (optional)", confirmRefuse: "Confirm", simple: "Simple electronic signature (code sent by email).", yousign: "A signature request has been emailed to you.", old: "This version has been replaced and can no longer be signed.", err: "Something went wrong" },
};

export function SignBox({ q, token, setQ, lang }) {
  const t = ST[lang];
  const [f, setF] = useState({ accept: false, name: "", title: "", code: "" });
  const [sent, setSent] = useState("");
  const [refuse, setRefuse] = useState(null);
  const [msg, setMsg] = useState("");
  const url = `${BASE}/api/public/quotes/${token}`;
  const fail = (e) => setMsg(typeof e.response?.data?.detail === "string" ? e.response.data.detail : t.err);
  if (!q.sign) return null;
  if (q.sign.status === "done") return <div className="card-soft mt-6 p-6 text-sm" data-testid="public-signed"><b>{t.signed}</b>{q.sign.signer_name && ` ${t.by} ${q.sign.signer_name}`} — {q.sign.signed_at?.slice(0, 10)}{q.sign.hash && <div className="mt-1 break-all text-xs text-muted-foreground">SHA-256 : {q.sign.hash}</div>}</div>;
  if (q.active === false) return <p className="mt-6 text-sm font-semibold text-amber-600" data-testid="public-old-version">{t.old}</p>;
  if (!q.sign.can) return null;
  if (q.sign.provider === "yousign") return <p className="mt-6 text-sm" data-testid="public-sign-yousign">{t.yousign}</p>;
  const inp = "h-10 w-full rounded-lg border border-border bg-background px-3 text-sm";
  return (
    <div className="card-soft mt-6 space-y-3 p-6" data-testid="public-sign">
      <label className="flex items-center gap-2 text-sm font-semibold"><input type="checkbox" className="h-5 w-5" checked={f.accept} onChange={(e) => setF({ ...f, accept: e.target.checked })} data-testid="sign-accept" />{t.accept}</label>
      <div className="grid grid-cols-1 gap-2 sm:grid-cols-2"><input className={inp} placeholder={t.name} value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} data-testid="sign-name" /><input className={inp} placeholder={t.title} value={f.title} onChange={(e) => setF({ ...f, title: e.target.value })} data-testid="sign-title" /></div>
      <button type="button" disabled={!f.accept || f.name.trim().length < 2} onClick={() => axios.post(`${url}/sign/request`).then((r) => { setSent(r.data.to); setMsg(""); }).catch(fail)} className="h-10 rounded-full border border-border px-5 text-sm font-semibold disabled:opacity-50" data-testid="sign-request">{t.get}</button>
      {sent && <><p className="text-xs text-muted-foreground" data-testid="sign-sent">{t.sent} {sent}</p>
        <div className="flex flex-wrap gap-2"><input className={`${inp} max-w-56`} inputMode="numeric" maxLength={6} placeholder={t.code} value={f.code} onChange={(e) => setF({ ...f, code: e.target.value.replace(/\D/g, "") })} data-testid="sign-code" />
          <button type="button" disabled={f.code.length !== 6} onClick={() => axios.post(`${url}/sign/confirm`, f).then((r) => setQ(r.data)).catch(fail)} className="h-10 rounded-full bg-foreground px-5 text-sm font-semibold text-background disabled:opacity-50" data-testid="sign-confirm">{t.sign}</button></div></>}
      {msg && <p className="text-sm text-red-600" data-testid="sign-error">{msg}</p>}
      <p className="text-xs text-muted-foreground">{t.simple}</p>
      {refuse === null ? <button type="button" className="text-xs underline" onClick={() => setRefuse("")} data-testid="sign-refuse">{t.refuse}</button> : (
        <div className="flex flex-wrap gap-2"><input className={`${inp} max-w-sm`} placeholder={t.reason} value={refuse} onChange={(e) => setRefuse(e.target.value)} data-testid="refuse-reason" /><button type="button" className="h-10 rounded-full border border-border px-5 text-sm font-semibold" onClick={() => axios.post(`${url}/refuse`, { reason: refuse }).then((r) => setQ(r.data)).catch(fail)} data-testid="refuse-confirm">{t.confirmRefuse}</button></div>
      )}
    </div>
  );
}

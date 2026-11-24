import { useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { PageHeader } from "@/components/common";
import { api, errMsg } from "@/lib/api";

const Stat = ({ label, value, testid }) => <div className="rounded-xl border border-border p-3"><div className="text-xs text-muted-foreground">{label}</div><div className="font-display text-2xl" data-testid={testid}>{value}</div></div>;
const Split = ({ title, data }) => (
  <div className="card-soft p-4"><div className="mb-2 text-sm font-semibold">{title} (créés / mis à jour / inchangés)</div>
    {Object.entries(data).sort().map(([k, v]) => <div key={k} className="flex justify-between border-b border-border py-1 text-sm last:border-0"><span>{k}</span><span className="text-muted-foreground">{v.created} / {v.updated} / {v.unchanged}</span></div>)}</div>
);

export default function ImportCatalogue() {
  const [rows, setRows] = useState(null);
  const [name, setName] = useState("");
  const [rep, setRep] = useState(null);
  const [busy, setBusy] = useState(false);
  const call = (list, apply) => { setBusy(true); return api.post("/catalogue-import", { rows: list, apply }).then((r) => { setRep(r.data); if (apply) toast.success("Import terminé"); }).catch((e) => toast.error(errMsg(e))).finally(() => setBusy(false)); };
  const pick = async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    try {
      const list = JSON.parse(await file.text());
      if (!Array.isArray(list)) throw new Error();
      setRows(list); setName(file.name); setRep(null);
      call(list, false);
    } catch { toast.error("Fichier illisible : une liste JSON de produits est attendue"); }
  };
  return (
    <div data-testid="catalogue-import-page">
      <PageHeader eyebrow="Parc matériel" title="Importer le catalogue" subtitle="Déposez le fichier JSON du catalogue Odoo. Un aperçu est calculé sans rien écrire ; l'import n'est lancé qu'après votre confirmation. Relancer l'import ne crée aucun doublon (mise à jour par référence)." />
      <div className="card-soft mb-4 flex flex-wrap items-center gap-3 p-4">
        <input type="file" accept="application/json,.json" onChange={pick} data-testid="catalogue-import-file" />
        {name && <span className="text-sm text-muted-foreground">{name} · {rows.length} lignes</span>}
        {busy && <span className="text-sm">Calcul en cours…</span>}
      </div>
      {rep && <div className="space-y-4" data-testid="catalogue-import-report">
        <div className={`rounded-xl p-3 text-sm font-semibold ${rep.applied ? "bg-emerald-500/10 text-emerald-700" : "bg-amber-500/10 text-amber-700"}`} data-testid="catalogue-import-mode">{rep.applied ? "Import appliqué." : "Aperçu : rien n'a été écrit."} Entrepôt : {rep.warehouse}</div>
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          <Stat label="Créés" value={rep.created} testid="import-created" /><Stat label="Mis à jour" value={rep.updated} testid="import-updated" /><Stat label="Ignorés (inchangés)" value={rep.unchanged} testid="import-unchanged" /><Stat label="Refusés" value={rep.refused.length} testid="import-refused" />
          <Stat label="Niveaux de stock créés" value={rep.stock_levels} testid="import-stock" /><Stat label="Unités en stock" value={rep.stock_units} /><Stat label="Prix à définir" value={rep.price_missing} /><Stat label="À vérifier" value={rep.to_check} />
        </div>
        {rep.refused.length > 0 && <div className="card-soft p-4 text-sm" data-testid="import-refused-list"><div className="mb-1 font-semibold">Lignes refusées</div>{rep.refused.map((r) => <div key={r.line}>Ligne {r.line} {r.ref} : {r.reason}</div>)}</div>}
        {rep.rounded.length > 0 && <p className="text-sm text-muted-foreground">Stocks décimaux arrondis à l'entier inférieur : {rep.rounded.join(" ; ")}</p>}
        {rep.existing_not_imported.length > 0 && <p className="text-sm text-amber-700">Produits déjà présents qui seraient mis à jour : {rep.existing_not_imported.join(", ")}</p>}
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2"><Split title="Par type" data={rep.by_type} /><Split title="Par catégorie" data={rep.by_category} /></div>
        {!rep.applied && <Button disabled={busy || !(rep.created + rep.updated)} onClick={() => window.confirm(`Importer ${rep.created} produit(s) et en mettre à jour ${rep.updated} dans le catalogue ?`) && call(rows, true)} data-testid="catalogue-import-confirm">Confirmer l'import</Button>}
      </div>}
    </div>
  );
}

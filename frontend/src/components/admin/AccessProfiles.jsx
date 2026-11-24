import { useCallback, useEffect, useState } from "react";
import { TrashDialog } from "@/components/Trash";
import { toast } from "sonner";
import { Plus, Copy, Pencil, Trash2, Lock } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogDescription } from "@/components/ui/dialog";
import { Section, Field, Loading } from "@/components/common";
import { api, errMsg } from "@/lib/api";
import { useMe } from "@/context/MeContext";

const ko = (e) => toast.error(errMsg(e));
const MODULES = { events: "Événements", finance: "Devis, factures & comptabilité", catalog: "Matériel & stock", contacts: "Contacts", venues: "Lieux", team: "Équipe", messages: "Messagerie", crm: "CRM", providers: "Prestataires & staff", org: "Paramètres de l'entreprise", users: "Membres & accès" };
const ACTIONS = { read: "Voir", write: "Créer / modifier", delete: "Supprimer", manage: "Gérer" };
const sel = "h-9 rounded-lg border border-border bg-background px-2 text-sm";

const SENS = { sale_prices: "Prix de vente et montants des devis / factures", costs_margins: "Coûts d'achat, tarifs prestataires et marges", client_contacts: "Coordonnées des clients (e-mail, téléphone, adresse)", hr_data: "Données RH (IBAN, n° de sécurité sociale)" };
const permLabel = (k) => `${MODULES[k.split(":")[0]] || k.split(":")[0]} — ${ACTIONS[k.split(":")[1]] || k.split(":")[1]}`;

export function OverridesDialog({ u, all, onClose, onSaved }) {
  const [rows, setRows] = useState(Object.fromEntries((u.permission_overrides || []).map((o) => [o.perm, o])));
  const set = (perm, v) => { const n = { ...rows }; if (v === "") delete n[perm]; else n[perm] = { perm, grant: v === "grant", expires_at: n[perm]?.expires_at || "" }; setRows(n); };
  const save = (list) => api.put(`/users/${u.user_id}/overrides`, { overrides: list }).then(() => { toast.success(list.length ? "Droits ajustés" : "Membre revenu aux droits de son profil"); onSaved(); onClose(); }).catch(ko);
  return (
    <Dialog open onOpenChange={onClose}>
      <DialogContent className="max-h-[92vh] max-w-2xl overflow-y-auto" data-testid="overrides-dialog">
        <DialogHeader><DialogTitle className="text-xl font-bold">Ajuster les droits de {u.name}</DialogTitle><DialogDescription>Ajoutez ou retirez un droit par rapport à son profil. Avec une date de fin, l'ajustement s'arrête tout seul le lendemain.</DialogDescription></DialogHeader>
        <div className="divide-y divide-border text-sm">
          {all.map((k) => (
            <div key={k} className="flex flex-wrap items-center gap-2 py-1.5"><span className="flex-1">{permLabel(k)}</span>
              <select className={sel} value={rows[k] ? (rows[k].grant ? "grant" : "deny") : ""} onChange={(e) => set(k, e.target.value)} data-testid={`override-${k}`}><option value="">Selon le profil</option><option value="grant">Accorder</option><option value="deny">Retirer</option></select>
              {rows[k] && <Input type="date" className="h-9 w-40" value={rows[k].expires_at} onChange={(e) => setRows({ ...rows, [k]: { ...rows[k], expires_at: e.target.value } })} aria-label="Date de fin" data-testid={`override-end-${k}`} />}
            </div>))}
        </div>
        <DialogFooter className="gap-2"><Button variant="outline" onClick={() => save([])} data-testid="overrides-reset">Revenir au profil</Button><Button onClick={() => save(Object.values(rows))} data-testid="overrides-save">Enregistrer</Button></DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

const COLS = { view: "Voir", create: "Créer", update: "Modifier", delete: "Supprimer", export: "Exporter", validate: "Valider" };
const SCOPE = { all: "Tout", assigned: "Événements où il est affecté", own: "Ses propres éléments" };
const SWITCHES = { send_client_messages: "Envoyer des messages clients au nom de la société", send_quotes_invoices: "Envoyer / faire signer un devis, relancer une facture" };

function ProfileDialog({ p, modules, mine, onClose, onSaved }) {
  const full = Object.fromEntries(modules.map((m) => [m.key, { ...Object.fromEntries(m.actions.map((a) => [a, true])), scope: "all" }]));
  const [f, setF] = useState({ name: p.name || "", name_en: p.name_en || "", description: p.description || "", permissions: p.locked ? full : p.permissions || {}, require_2fa: p.require_2fa || "optional", sensitive: { ...(p.sensitive || {}) } });
  const ro = p.locked || (p.id && p.id === mine);
  const row = (k) => f.permissions[k] || {};
  const setRow = (k, v) => setF({ ...f, permissions: { ...f.permissions, [k]: { scope: "all", ...row(k), ...v } } });
  const fill = (m, on) => setRow(m.key, Object.fromEntries(m.actions.map((a) => [a, on(a)])));
  const tick = (m, a, v) => setRow(m.key, a === "view" && !v ? Object.fromEntries(m.actions.map((x) => [x, false])) : { [a]: v, ...(v ? { view: true } : {}) });
  const save = async () => { try { await (p.id ? api.put(`/access-profiles/${p.id}`, f) : api.post("/access-profiles", f)); toast.success("Profil enregistré"); onSaved(); onClose(); } catch (e) { ko(e); } };
  return (
    <Dialog open onOpenChange={onClose}>
      <DialogContent className="max-h-[92vh] max-w-5xl overflow-y-auto" data-testid="profile-dialog">
        <DialogHeader><DialogTitle className="text-xl font-bold">{p.id ? `Profil ${p.name}` : "Nouveau profil d'accès"}</DialogTitle><DialogDescription>{p.locked ? "Profil Administrateur : accès à tout, non modifiable." : p.id === mine ? "C'est votre propre profil : vous ne pouvez pas le modifier." : "Cochez, module par module, ce que les membres de ce profil peuvent faire. Le changement s'applique dès leur prochaine action. Un module sans « Voir » disparaît du menu."}</DialogDescription></DialogHeader>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <Field label="Nom"><Input disabled={ro} value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} data-testid="profile-name" /></Field>
          <Field label="Double authentification (application ou passkey)"><select disabled={ro} className={`${sel} w-full`} value={f.require_2fa} onChange={(e) => setF({ ...f, require_2fa: e.target.value })} data-testid="profile-2fa"><option value="optional">Facultative</option><option value="required">Obligatoire pour ce profil</option></select></Field>
        </div>
        <div className="overflow-x-auto rounded-2xl border border-border" data-testid="profile-grid">
          <table className="w-full text-sm">
            <thead><tr className="border-b border-border text-left text-xs text-muted-foreground"><th className="p-2">Module</th>{Object.values(COLS).map((c) => <th key={c} className="p-2 text-center">{c}</th>)}<th className="p-2">Portée</th>{!ro && <th className="p-2">Raccourcis</th>}</tr></thead>
            <tbody>{modules.map((m) => (
              <tr key={m.key} className="border-b border-border last:border-0" data-testid={`grid-row-${m.key}`}>
                <td className="p-2 font-semibold">{m.label}</td>
                {Object.keys(COLS).map((a) => <td key={a} className="p-2 text-center">{m.actions.includes(a) ? <input type="checkbox" disabled={ro} checked={!!row(m.key)[a]} onChange={(e) => tick(m, a, e.target.checked)} aria-label={`${m.label} : ${COLS[a]}`} data-testid={`grid-${m.key}-${a}`} /> : <span className="text-muted-foreground">·</span>}</td>)}
                <td className="p-2">{m.scopes.length > 0 ? <select disabled={ro} className={sel} value={row(m.key).scope || "all"} onChange={(e) => setRow(m.key, { scope: e.target.value })} data-testid={`grid-${m.key}-scope`}>{m.scopes.map((x) => <option key={x} value={x}>{SCOPE[x]}</option>)}</select> : <span className="text-xs text-muted-foreground">Tout</span>}</td>
                {!ro && <td className="whitespace-nowrap p-2 text-xs"><button type="button" className="underline" onClick={() => fill(m, () => true)} data-testid={`grid-${m.key}-all`}>Tout</button> · <button type="button" className="underline" onClick={() => fill(m, (a) => a === "view")} data-testid={`grid-${m.key}-read`}>Lecture</button> · <button type="button" className="underline" onClick={() => fill(m, () => false)} data-testid={`grid-${m.key}-none`}>Aucun</button></td>}
              </tr>))}</tbody>
          </table>
        </div>
        <div className="rounded-2xl border border-border p-3 text-sm" data-testid="profile-sensitive"><div className="mb-1 font-semibold">Données sensibles visibles et actions autorisées</div>
          {Object.entries({ ...SENS, ...SWITCHES }).map(([k, l]) => <label key={k} className="flex items-center gap-2 py-0.5"><input type="checkbox" disabled={ro} checked={p.locked || f.sensitive[k] !== false} onChange={(e) => setF({ ...f, sensitive: { ...f.sensitive, [k]: e.target.checked } })} data-testid={`profile-sensitive-${k}`} />{l}</label>)}
          <label className="flex items-center gap-2 py-0.5"><input type="checkbox" disabled={ro} checked={p.locked || f.sensitive.finance_costs === true} onChange={(e) => setF({ ...f, sensitive: { ...f.sensitive, finance_costs: e.target.checked } })} data-testid="profile-sensitive-finance_costs" />Voir les prix d'achat, marges, fournisseurs et le pôle Achats (finance:costs)</label>
          <label className="mt-1 flex flex-wrap items-center gap-2">Valider des dépenses jusqu'à <Input type="number" min="0" disabled={ro} className="h-8 w-28" placeholder="sans limite" value={f.sensitive.expense_validation_limit || ""} onChange={(e) => setF({ ...f, sensitive: { ...f.sensitive, expense_validation_limit: Number(e.target.value) || null } })} data-testid="profile-expense-limit" /> € (vide = sans limite)</label>
          <p className="mt-1 text-xs text-muted-foreground">Décoché : ces données sont retirées des réponses du serveur pour ce profil, et les PDF / exports de devis et factures sont refusés.</p></div>
        {!ro && <DialogFooter><Button onClick={save} data-testid="profile-save">Enregistrer</Button></DialogFooter>}
      </DialogContent>
    </Dialog>
  );
}

const MSTATUS = { active: ["Actif", "bg-emerald-50 text-emerald-700"], invited: ["Invité", "bg-blue-500/10 text-blue-600"], suspended: ["Suspendu", "bg-amber-500/15 text-amber-700"], disabled: ["Désactivé", "bg-red-500/15 text-red-600"] };

export function ManageDialog({ u, users, onClose, onSaved }) {
  const [counts, setCounts] = useState(null);
  const [to, setTo] = useState("");
  useEffect(() => { api.get(`/members/${u.user_id}/handover`).then((r) => setCounts(r.data)).catch(ko); }, [u]);
  const act = (a, msg, confirm) => (!confirm || window.confirm(confirm)) && api.post(`/members/${u.user_id}/do/${a}`).then(() => { toast.success(msg); onSaved(); onClose(); }).catch(ko);
  const transfer = () => api.post(`/members/${u.user_id}/handover`, { to_user_id: to }).then((r) => { toast.success(`Transféré : ${Object.entries(r.data).map(([k, n]) => `${n} ${k}`).join(", ")}`); api.get(`/members/${u.user_id}/handover`).then((x) => setCounts(x.data)); }).catch(ko);
  const off = ["suspended", "disabled"].includes(u.status);
  return (
    <Dialog open onOpenChange={onClose}>
      <DialogContent className="max-w-xl" data-testid="member-manage-dialog">
        <DialogHeader><DialogTitle className="text-xl font-bold">Gérer {u.name}</DialogTitle><DialogDescription>{u.email}{u.end_date ? ` · fin de contrat le ${u.end_date}` : ""} · 2FA : {u.two_factor ? "activée" : "non activée"}</DialogDescription></DialogHeader>
        <div className="rounded-2xl border border-border p-3 text-sm" data-testid="member-handover"><div className="font-semibold">Transfert avant un départ</div>
          <p className="my-1 text-muted-foreground" data-testid="member-handover-counts">{counts ? `${counts.tasks} tâche(s) ouverte(s), ${counts.events} événement(s) à venir, ${counts.opportunities} opportunité(s) CRM en cours.` : "…"} Son historique reste à son nom.</p>
          <div className="flex flex-wrap gap-2"><select className={`${sel} flex-1`} value={to} onChange={(e) => setTo(e.target.value)} data-testid="member-handover-to"><option value="">Transférer à…</option>{users.filter((x) => x.user_id !== u.user_id && !["suspended", "disabled"].includes(x.status)).map((x) => <option key={x.user_id} value={x.user_id}>{x.name}</option>)}</select>
            <Button size="sm" disabled={!to} onClick={transfer} data-testid="member-handover-submit">Transférer</Button></div></div>
        <div className="flex flex-wrap gap-2">
          {off ? <Button size="sm" variant="outline" onClick={() => act("reactivate", "Membre réactivé")} data-testid="member-reactivate">Réactiver</Button> : <Button size="sm" variant="outline" onClick={() => act("suspend", "Membre suspendu")} data-testid="member-suspend">Suspendre</Button>}
          <Button size="sm" variant="outline" onClick={() => act("revoke", "Sessions révoquées")} data-testid="member-revoke">Révoquer les sessions</Button>
          <Button size="sm" variant="outline" onClick={() => act("reset-2fa", "2FA réinitialisée")} data-testid="member-reset-2fa">Réinitialiser la 2FA</Button>
          {u.status !== "disabled" && <Button size="sm" variant="destructive" onClick={() => act("disable", "Membre désactivé", `Désactiver ${u.name} ? Il ne pourra plus se connecter.`)} data-testid="member-disable">Désactiver</Button>}
        </div>
      </DialogContent>
    </Dialog>
  );
}

export function AccessProfiles() {
  const { me } = useMe();
  const [d, setD] = useState(null);
  const [edit, setEdit] = useState(null);
  const [del, setDel] = useState(null);
  const viewAs = (u) => { sessionStorage.setItem("view-as-member", u.user_id); window.location.href = "/dashboard"; };
  const load = useCallback(() => api.get("/access-profiles").then((r) => setD(r.data)).catch(ko), []);
  useEffect(() => { load(); }, [load]);
  if (!d) return <Loading />;
  if (!d.active) return (
    <Section title="Profils d'accès">
      <p className="mb-3 max-w-2xl text-sm text-muted-foreground">Les profils d'accès ne sont pas encore activés pour cette société : les rôles actuels restent en vigueur. L'activation crée les profils par défaut et rattache chaque membre au profil qui correspond exactement à ses droits actuels.</p>
      <Button onClick={() => window.confirm("Activer les profils d'accès pour cette société ? Les droits actuels de chaque membre sont conservés.") && api.post("/access-profiles/activate").then((r) => { toast.success(`Profils activés : ${r.data.members.length} membre(s) rattaché(s)`); load(); }).catch(ko)} data-testid="profiles-activate">Activer les profils d'accès</Button>
    </Section>
  );
  return (
    <div className="space-y-6" data-testid="access-profiles">
      <Section title="Profils d'accès" actions={<Button size="sm" onClick={() => setEdit({})} data-testid="profile-new"><Plus />Profil</Button>}>
        <div className="divide-y divide-border">{d.profiles.map((p) => (
          <div key={p.id} className="flex flex-wrap items-center gap-3 py-2.5 text-sm" data-testid={`profile-row-${p.name}`}>
            {p.locked && <Lock className="h-3.5 w-3.5" />}<span className="font-semibold">{p.name}</span><span className="text-xs text-muted-foreground">{p.members} membre(s) · {p.locked ? "accès à tout" : `${Object.values(p.permissions || {}).filter((r) => r.view).length} module(s) visibles`}{p.scope === "assigned" ? " · événements affectés" : ""}{p.require_2fa === "required" ? " · 2FA obligatoire" : ""}{p.is_system ? "" : " · personnalisé"}</span>
            <span className="ml-auto" />
            <Button size="sm" variant="ghost" onClick={() => setEdit(p)} data-testid={`profile-edit-${p.name}`}><Pencil />{p.locked || p.id === d.my_profile_id ? "Voir" : "Modifier"}</Button>
            <Button size="sm" variant="ghost" onClick={() => setEdit({ ...p, id: undefined, locked: false, name: `${p.name} (copie)` })} data-testid={`profile-duplicate-${p.name}`}><Copy />Dupliquer</Button>
            {(() => { const why = p.is_system || p.locked ? "Profil par défaut : non supprimable" : p.members > 0 ? "Des membres y sont rattachés : changez d'abord leur profil" : ""; return <span className="flex items-center gap-2"><Button size="sm" variant="ghost" className="text-red-600" disabled={!!why} title={why} onClick={() => setDel(p)} data-testid={`profile-delete-${p.name}`}><Trash2 />Supprimer</Button>{why && <span className="max-w-[14rem] text-[11px] text-muted-foreground" data-testid={`profile-delete-why-${p.name}`}>{why}</span>}</span>; })()}
          </div>))}</div>
      </Section>
      {del && <TrashDialog items={[{ kind: "profile", id: del.id, name: del.name }]} onClose={() => setDel(null)} onDone={load} />}
      {edit && <ProfileDialog p={edit} modules={d.modules} mine={d.my_profile_id} onClose={() => setEdit(null)} onSaved={load} />}
    </div>
  );
}

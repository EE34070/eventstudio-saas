import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { MoreHorizontal, Pencil, UserPlus } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from "@/components/ui/dialog";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { Section, Field, Loading } from "@/components/common";
import { api, errMsg } from "@/lib/api";
import { useMe } from "@/context/MeContext";
import { TrashDialog, BulkDelete } from "@/components/Trash";

const ko = (e) => toast.error(errMsg(e));
const sel = "h-9 w-full rounded-lg border border-border bg-background px-2 text-sm";
const ST = { active: ["Actif", "bg-emerald-50 text-emerald-700"], invited: ["Invité", "bg-blue-500/10 text-blue-600"], suspended: ["Suspendu", "bg-amber-500/15 text-amber-700"], disabled: ["Désactivé", "bg-red-500/15 text-red-600"] };
const FILTERS = [["active", "Actifs"], ["invited", "Invités"], ["suspended", "Suspendus"], ["disabled", "Désactivés"]];
const CONTRACTS = { cdi: "CDI", cdd: "CDD", cddu: "CDDU (intermittent)", alternance: "Alternance", stage: "Stage", independant: "Indépendant", externe: "Externe", autre: "Autre" };
const LANGS = [["fr-FR", "Français"], ["en-GB", "English"], ["es-ES", "Español"], ["it-IT", "Italiano"], ["de-DE", "Deutsch"]];

function EditDialog({ m, profiles, onClose, onSaved, onDelete }) {
  const [f, setF] = useState({ ...m, status: m.status });
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value });
  const photo = (file) => { const fd = new FormData(); fd.append("file", file); api.post("/files", fd).then((r) => setF((x) => ({ ...x, photo: r.data.ref }))).catch(ko); };
  const save = (e) => {
    e.preventDefault();
    api.put(`/members/${m.id}`, { first_name: f.first_name, last_name: f.last_name, email: f.email, phone: f.phone, photo: f.photo || "", job: f.job, contract_type: f.contract_type, start_date: f.start_date || "", end_date: f.end_date || "", language: f.language, profile_id: f.profile_id || "", status: f.status })
      .then((r) => { toast.success(r.data.invitation_resent ? "Membre modifié, invitation renvoyée à la nouvelle adresse" : "Membre modifié"); onSaved(); onClose(); }).catch(ko);
  };
  return (
    <Dialog open onOpenChange={onClose}><DialogContent className="max-h-[92vh] max-w-xl overflow-y-auto" data-testid="member-edit-dialog">
      <DialogHeader><DialogTitle>Modifier {m.name}</DialogTitle><DialogDescription>Un changement de profil s'applique dès la requête suivante du membre, sans reconnexion.</DialogDescription></DialogHeader>
      <form onSubmit={save} className="grid grid-cols-2 gap-3">
        <Field label="Prénom"><Input required value={f.first_name || ""} onChange={set("first_name")} data-testid="member-edit-first-name" /></Field>
        <Field label="Nom"><Input value={f.last_name || ""} onChange={set("last_name")} data-testid="member-edit-last-name" /></Field>
        <Field label="E-mail"><Input type="email" value={f.email || ""} onChange={set("email")} data-testid="member-edit-email" /></Field>
        <Field label="Téléphone"><Input value={f.phone || ""} onChange={set("phone")} data-testid="member-edit-phone" /></Field>
        <Field label="Poste"><Input value={f.job || ""} onChange={set("job")} data-testid="member-edit-job" /></Field>
        <Field label="Type de contrat"><select className={sel} value={f.contract_type} onChange={set("contract_type")} data-testid="member-edit-contract">{Object.entries(CONTRACTS).map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select></Field>
        <Field label="Date d'entrée"><Input type="date" value={f.start_date || ""} onChange={set("start_date")} data-testid="member-edit-start" /></Field>
        <Field label="Date de fin"><Input type="date" value={f.end_date || ""} onChange={set("end_date")} data-testid="member-edit-end" /></Field>
        <Field label="Langue"><select className={sel} value={f.language} onChange={set("language")} data-testid="member-edit-language">{LANGS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select></Field>
        <Field label="Profil d'accès"><select className={sel} disabled={m.is_self || !profiles.length} value={f.profile_id || ""} onChange={set("profile_id")} data-testid="member-edit-profile">{!f.profile_id && <option value="">—</option>}{profiles.filter((p) => m.user_id || p.base_role).map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}</select></Field>
        <Field label="Statut"><select className={sel} disabled={m.is_self} value={f.status} onChange={set("status")} data-testid="member-edit-status">{(m.user_id ? ["active", "suspended", "disabled"] : ["invited", "disabled"]).map((k) => <option key={k} value={k}>{ST[k][0]}</option>)}</select></Field>
        <Field label={`Photo${f.photo ? " (déposée)" : ""}`}><input type="file" accept="image/*" onChange={(e) => e.target.files[0] && photo(e.target.files[0])} data-testid="member-edit-photo" /></Field>
        {f.email !== m.email && <p className="col-span-2 rounded-xl bg-secondary p-3 text-xs text-muted-foreground" data-testid="member-edit-email-note">{m.user_id ? "L'adresse de connexion du membre sera remplacée." : "L'ancien lien d'invitation sera invalidé et une invitation partira à la nouvelle adresse."}</p>}
        <DialogFooter className="col-span-2 items-center sm:justify-between"><span className="flex items-center gap-2"><Button type="button" variant="outline" className="text-red-600" disabled={!!m.delete_block} onClick={onDelete} data-testid="member-edit-delete">Supprimer</Button>{m.delete_block && <span className="text-xs text-muted-foreground" data-testid="member-edit-delete-why">{m.delete_block}</span>}</span><Button data-testid="member-edit-save">Enregistrer</Button></DialogFooter>
      </form>
    </DialogContent></Dialog>);
}

function InviteDialog({ onClose, onSaved }) {
  const { me } = useMe();
  const [f, setF] = useState({ first: "", last: "", email: "", access_role: "technicien" });
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value });
  const save = (e) => { e.preventDefault(); api.post("/team", { name: `${f.first} ${f.last}`.trim(), email: f.email.trim(), access_role: f.access_role, send_invite: true }).then((r) => { const a = r.data.access || {}; a.status === "sent" ? toast.success("Invitation envoyée") : toast.error(`Membre créé, invitation NON envoyée : ${a.error || "copiez le lien depuis le menu ⋯"}`, { duration: 12000 }); onSaved(); onClose(); }).catch(ko); };
  return (
    <Dialog open onOpenChange={onClose}><DialogContent data-testid="member-invite-dialog"><DialogHeader><DialogTitle>Inviter un membre</DialogTitle><DialogDescription>Il reçoit un e-mail avec un lien pour créer son accès. Le profil se règle ensuite dans la fiche.</DialogDescription></DialogHeader>
      <form onSubmit={save} className="grid grid-cols-2 gap-3">
        <Field label="Prénom"><Input required value={f.first} onChange={set("first")} data-testid="member-invite-first" /></Field>
        <Field label="Nom"><Input value={f.last} onChange={set("last")} data-testid="member-invite-last" /></Field>
        <Field label="E-mail" className="col-span-2"><Input required type="email" value={f.email} onChange={set("email")} data-testid="member-invite-email" /></Field>
        <Field label="Rôle" className="col-span-2"><select className="h-10 w-full rounded-lg border border-border bg-background px-3 text-sm" value={f.access_role} onChange={set("access_role")} data-testid="member-invite-role">{(me?.roles || []).map((r) => <option key={r.id} value={r.id}>{r.label}</option>)}</select></Field>
        <DialogFooter className="col-span-2"><Button data-testid="member-invite-submit">Envoyer l'invitation</Button></DialogFooter>
      </form></DialogContent></Dialog>);
}

export function Members({ onAdjust, onManage, refreshKey }) {
  const { reload } = useMe();
  const [d, setD] = useState(null);
  const [show, setShow] = useState(["active", "invited", "suspended", "disabled"]);
  const [edit, setEdit] = useState(null);
  const [del, setDel] = useState(null);
  const [pick, setPick] = useState([]);
  const [inv, setInv] = useState(false);
  const copyLink = (m) => api.get(`/team/${m.id}/invite-link`).then((r) => navigator.clipboard.writeText(r.data.link).then(() => toast.success("Lien d'invitation copié"), () => window.prompt("Copiez ce lien d'invitation", r.data.link))).catch(ko);
  const load = useCallback(() => api.get("/members").then((r) => setD(r.data)).catch(ko), []);
  useEffect(() => { load(); }, [load, refreshKey]);
  if (!d) return <Loading />;
  const after = () => { load(); reload(); };
  const act = (m, a, msg) => api.post(`/members/${m.user_id}/do/${a}`).then(() => { toast.success(msg); after(); }).catch(ko);
  const setStatus = (m, status, msg) => api.put(`/members/${m.id}`, { first_name: m.first_name || m.name, last_name: m.last_name || "", email: m.email, phone: m.phone, photo: m.photo || "", job: m.job, contract_type: m.contract_type, start_date: m.start_date || "", end_date: m.end_date || "", language: m.language, profile_id: "", status }).then(() => { toast.success(msg); after(); }).catch(ko);
  const invite = (m) => api.post(`/team/${m.id}/invite`).then((r) => (r.data.access.status === "sent" ? toast.success("Invitation envoyée") : toast.error(`Invitation non envoyée : ${r.data.access.error}`, { duration: 12000 }))).then(load).catch(ko);
  const openEdit = (m) => (m.id ? setEdit(m) : api.post(`/members/${m.user_id}/sheet`).then((r) => { load(); setEdit({ contract_type: "cdi", language: "fr-FR", ...m, id: r.data.id }); }).catch(ko));
  const askDel = (m) => (m.id ? setDel(m) : api.post(`/members/${m.user_id}/sheet`).then((r) => setDel({ ...m, id: r.data.id })).catch(ko));
  const rows = d.rows.filter((m) => show.includes(m.status));
  const prof = (m) => d.profiles.find((p) => p.id === m.profile_id);
  return (
    <Section title="Membres" actions={<Button size="sm" onClick={() => setInv(true)} data-testid="members-invite"><UserPlus />Inviter un membre</Button>}>
      <div className="mb-3 flex flex-wrap gap-1.5" data-testid="members-filter">{FILTERS.map(([k, l]) => { const on = show.includes(k); return <button key={k} aria-pressed={on} onClick={() => setShow(on ? show.filter((x) => x !== k) : [...show, k])} data-testid={`members-filter-${k}`} className={`h-8 rounded-full border px-3 text-xs font-semibold ${on ? "border-primary bg-primary text-white" : "border-border"}`}>{l} ({d.rows.filter((m) => m.status === k).length})</button>; })}<span className="ml-auto" /><BulkDelete kind="member" picked={pick} onDone={() => { setPick([]); after(); }} /></div>
      <div className="divide-y divide-border" data-testid="members-list">{rows.length === 0 && <p className="py-3 text-sm text-muted-foreground">Aucun membre pour ce filtre.</p>}{rows.map((m) => {
        const locked = prof(m)?.locked; const manageable = !m.is_self && (d.my_locked || !locked); const off = ["suspended", "disabled"].includes(m.status);
        return (
          <div key={m.id || m.user_id} className="flex flex-wrap items-center gap-3 py-2.5 text-sm" data-testid={`member-row-${m.email || m.id}`}>
            {m.id && !m.delete_block && <input type="checkbox" checked={pick.includes(m.id)} onChange={(e) => setPick(e.target.checked ? [...pick, m.id] : pick.filter((x) => x !== m.id))} data-testid={`member-pick-${m.email || m.id}`} />}<span className="font-semibold">{m.name}</span><span className="text-xs text-muted-foreground">{m.email}</span>
            <span className={`rounded-full px-2 py-0.5 text-[11px] font-semibold ${ST[m.status][1]}`} data-testid={`member-row-status-${m.email || m.id}`}>{m.status === "invited" && m.invite === "none" ? "Non invité" : m.status === "invited" && m.invite === "error" ? "Erreur d'envoi" : ST[m.status][0]}</span>
            <span className="text-xs text-muted-foreground">{prof(m)?.name || m.access_role}{m.end_date ? ` · fin le ${m.end_date}` : ""}{m.overrides?.length ? ` · ${m.overrides.length} ajustement(s)` : ""}</span>
            <span className="ml-auto" />
            {<Button size="sm" variant="ghost" onClick={() => openEdit(m)} data-testid={`member-row-edit-${m.email || m.id}`}><Pencil />Modifier</Button>}
            <DropdownMenu><DropdownMenuTrigger asChild><Button size="icon" variant="ghost" aria-label="Actions" data-testid={`member-row-menu-${m.email || m.id}`}><MoreHorizontal className="h-4 w-4" /></Button></DropdownMenuTrigger>
              <DropdownMenuContent align="end" data-testid="member-row-menu-content">
                <DropdownMenuItem onClick={() => openEdit(m)} data-testid="member-menu-edit">Modifier</DropdownMenuItem>
                <DropdownMenuItem disabled={!m.user_id || !manageable || locked} onClick={() => onAdjust({ ...m, permission_overrides: m.overrides })} data-testid="member-menu-adjust">Ajuster les droits</DropdownMenuItem>
                <DropdownMenuItem disabled={!!m.user_id || !m.email || m.status === "disabled"} onClick={() => invite(m)} data-testid="member-menu-invite">Renvoyer l'invitation</DropdownMenuItem>
                <DropdownMenuItem disabled={!m.id || !!m.user_id || m.status === "disabled"} onClick={() => copyLink(m)} data-testid="member-menu-copy-link">Copier le lien</DropdownMenuItem>
                <DropdownMenuItem disabled={!m.user_id || !manageable || m.status === "disabled"} onClick={() => act(m, off ? "reactivate" : "suspend", off ? "Membre réactivé" : "Membre suspendu")} data-testid="member-menu-suspend">{m.status === "suspended" ? "Réactiver" : "Suspendre"}</DropdownMenuItem>
                <DropdownMenuItem disabled={!m.user_id || !manageable} onClick={() => act(m, "revoke", "Sessions révoquées")} data-testid="member-menu-revoke">Révoquer les sessions</DropdownMenuItem>
                <DropdownMenuSeparator />
                {m.status === "disabled"
                  ? <DropdownMenuItem disabled={m.is_self} onClick={() => (m.user_id ? act(m, "reactivate", "Membre réactivé") : setStatus(m, "invited", "Membre réactivé"))} data-testid="member-menu-reactivate">Réactiver</DropdownMenuItem>
                  : <DropdownMenuItem disabled={m.user_id ? !manageable : !m.id} onClick={() => (m.user_id ? onManage(m) : window.confirm(`Désactiver ${m.name} ? Son lien d'invitation sera invalidé.`) && setStatus(m, "disabled", "Membre désactivé"))} data-testid="member-menu-disable">Désactiver{m.user_id ? " (assistant de transfert)" : ""}</DropdownMenuItem>}
                <DropdownMenuItem disabled={!!m.delete_block} className="flex-col items-start text-red-600" onClick={() => askDel(m)} data-testid="member-menu-delete">Supprimer{m.delete_block && <span className="text-[11px] font-normal" data-testid="member-menu-delete-why">{m.delete_block}</span>}</DropdownMenuItem>
              </DropdownMenuContent></DropdownMenu>
          </div>);
      })}</div>
      {edit && <EditDialog m={edit} profiles={d.profiles} onClose={() => setEdit(null)} onSaved={after} onDelete={() => { const m = edit; setEdit(null); askDel(m); }} />}
      {inv && <InviteDialog onClose={() => setInv(false)} onSaved={after} />}
      {del && <TrashDialog items={[{ kind: "member", id: del.id, name: del.name }]} onClose={() => setDel(null)} onDone={after} />}
    </Section>);
}

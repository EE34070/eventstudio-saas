import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { toast } from "sonner";
import { Plus, Trash2, Pencil, CalendarCheck2, Send, Copy } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog";
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { PageHeader, Loading, Field, StatusBadge } from "@/components/common";
import { api, errMsg } from "@/lib/api";
import { fmtDT, fmtEur } from "@/lib/constants";
import { useMe } from "@/context/MeContext";

const EMPTY = { name: "", email: "", phone: "", job: "", access_role: "technicien", skills: [], color: "#B4643C", day_rate: 0, active: true, unavailabilities: [], contract_type: "cdi", licences: [], licence_valid_until: "", is_driver: false, start_date: "", end_date: "" };
const CONTRACTS = { cdi: "CDI", cdd: "CDD", cddu: "CDDU (intermittent)", alternance: "Alternance", stage: "Stage", independant: "Indépendant", externe: "Externe", autre: "Autre" };
const LICENCES = ["B", "BE", "C1", "C", "CE"];

const ACCESS = { none: ["Non invité", "bg-secondary text-muted-foreground"], sent: ["Invitation envoyée", "bg-blue-500/10 text-blue-600"], active: ["Actif", "bg-emerald-50 text-emerald-700"], suspended: ["Suspendu", "bg-amber-500/15 text-amber-700"], error: ["Erreur d'envoi", "bg-red-500/15 text-red-600"] };
const inviteMsg = (a) => (a.status === "sent" ? toast.success("Invitation envoyée par e-mail") : toast.error(`Invitation non envoyée : ${a.error}`, { duration: 12000 }));

function MemberAccess({ m, write, onChanged }) {
  const a = m.access || { status: "none" };
  const [label, cls] = ACCESS[a.status] || ACCESS.none;
  const when = a.invited_at ? new Date(a.invited_at).toLocaleString("fr-FR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" }).replace(" ", " à ") : "";
  const send = () => api.post(`/team/${m.id}/invite`).then((r) => { inviteMsg(r.data.access); onChanged(); }).catch((e) => toast.error(errMsg(e)));
  const copy = () => api.get(`/team/${m.id}/invite-link`).then((r) => navigator.clipboard.writeText(r.data.link).then(() => toast.success("Lien d'invitation copié : envoyez-le par WhatsApp ou SMS"), () => window.prompt("Copiez ce lien d'invitation", r.data.link))).catch((e) => toast.error(errMsg(e)));
  return (
    <div className="mt-3" data-testid={`member-access-${m.id}`}>
      <span className={`rounded-full px-2 py-0.5 text-[11px] font-semibold ${cls}`} data-testid={`member-access-status-${m.id}`}>{label}{a.status === "sent" && when ? ` le ${when}` : ""}</span>
      {a.status === "error" && <div className="mt-1 text-xs text-red-600" data-testid={`member-access-error-${m.id}`}>{a.error}</div>}
      {write && !["active", "suspended"].includes(a.status) && (
        <div className="mt-2 flex flex-wrap gap-2">
          {m.email ? <Button size="sm" variant="outline" onClick={send} data-testid={`member-invite-${m.id}`}><Send className="mr-1 h-3.5 w-3.5" />{a.status === "none" ? "Envoyer l'invitation" : "Renvoyer l'invitation"}</Button> : <span className="text-xs text-muted-foreground">Ajoutez un e-mail pour inviter ce membre.</span>}
          {a.has_link && <Button size="sm" variant="ghost" onClick={copy} data-testid={`member-invite-copy-${m.id}`}><Copy className="mr-1 h-3.5 w-3.5" />Copier le lien d'invitation</Button>}
        </div>
      )}
    </div>
  );
}

function MemberDialog({ open, onOpenChange, member, onSaved }) {
  const { me } = useMe();
  const [f, setF] = useState(EMPTY);
  const [invite, setInvite] = useState(true);
  useEffect(() => { if (open) setInvite(true); }, [open]);
  useEffect(() => { if (open) setF(member ? { ...EMPTY, ...Object.fromEntries(Object.keys(EMPTY).map((k) => [k, member[k] ?? EMPTY[k]])) } : EMPTY); }, [open, member]);
  const set = (k) => (e) => setF({ ...f, [k]: e?.target ? e.target.value : e });
  const linked = !!member?.user_id;
  const submit = async (e) => {
    e.preventDefault();
    const body = { ...f, day_rate: Number(f.day_rate) || 0, unavailabilities: f.unavailabilities.filter((u) => u.start && u.end) };
    try { const r = member ? await api.put(`/team/${member.id}`, body) : await api.post("/team", { ...body, send_invite: invite && !!body.email }); if (!member && invite && body.email) { if (r.data.access.status === "sent") toast.success("Membre enregistré, invitation envoyée par e-mail"); else toast.error(`Membre enregistré, mais invitation NON envoyée : ${r.data.access.error}`, { duration: 15000 }); } else toast.success("Membre enregistré"); onSaved(); onOpenChange(false); } catch (err) { toast.error(errMsg(err)); }
  };
  const un = f.unavailabilities;
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[92vh] max-w-xl overflow-y-auto">
        <DialogHeader><DialogTitle className="font-display text-2xl font-medium">{member ? "Modifier le membre" : "Nouveau membre"}</DialogTitle></DialogHeader>
        <form onSubmit={submit} className="grid grid-cols-2 gap-4" data-testid="member-form">
          <Field label="Nom"><Input required value={f.name} onChange={set("name")} data-testid="member-name-input" /></Field>
          <Field label="Poste / métier"><Input value={f.job} onChange={set("job")} data-testid="member-job-input" /></Field>
          <Field label="E-mail (invitation)"><Input type="email" disabled={linked} value={f.email} onChange={set("email")} data-testid="member-email-input" /></Field>
          <Field label="Téléphone"><Input value={f.phone} onChange={set("phone")} /></Field>
          <Field label="Rôle d'accès">
            <Select disabled={linked} value={f.access_role} onValueChange={set("access_role")}><SelectTrigger data-testid="member-role-select"><SelectValue /></SelectTrigger>
              <SelectContent>{me.roles.map((r) => <SelectItem key={r.id} value={r.id}>{r.label}</SelectItem>)}</SelectContent></Select>
          </Field>
          <Field label="Type de contrat">
            <Select value={f.contract_type} onValueChange={set("contract_type")}><SelectTrigger data-testid="member-contract-select"><SelectValue /></SelectTrigger>
              <SelectContent>{Object.entries(CONTRACTS).map(([k, l]) => <SelectItem key={k} value={k}>{l}</SelectItem>)}</SelectContent></Select>
          </Field>
          <Field label="Date d'entrée"><Input type="date" value={f.start_date} onChange={set("start_date")} data-testid="member-start-date" /></Field>
          <Field label="Date de fin de contrat (facultative)"><Input type="date" value={f.end_date} onChange={set("end_date")} data-testid="member-end-date" /></Field>
          {f.end_date && <p className="col-span-2 rounded-xl bg-secondary p-3 text-xs text-muted-foreground" data-testid="member-end-note">Rappel aux administrateurs 7 jours avant ; l'accès est désactivé automatiquement le lendemain de cette date.</p>}
          <Field label="Validité du permis"><Input type="date" value={f.licence_valid_until} onChange={set("licence_valid_until")} data-testid="member-licence-valid" /></Field>
          <div className="col-span-2 flex flex-wrap items-center gap-2"><span className="text-xs font-medium text-muted-foreground">Permis</span>{LICENCES.map((l) => { const on = f.licences.includes(l); return <button type="button" key={l} aria-pressed={on} onClick={() => setF({ ...f, licences: on ? f.licences.filter((x) => x !== l) : [...f.licences, l] })} data-testid={`member-licence-${l}`} className={`h-8 rounded-full border px-3 text-xs font-semibold ${on ? "border-primary bg-primary text-white" : "border-border"}`}>{l}</button>; })}<label className="ml-auto flex items-center gap-2 text-sm"><Switch checked={f.is_driver} onCheckedChange={set("is_driver")} data-testid="member-driver-switch" />Chauffeur</label></div>
          {f.contract_type === "cddu" && <p className="col-span-2 rounded-xl bg-secondary p-3 text-xs text-muted-foreground" data-testid="member-cddu-note">Salarié en CDDU = intermittent : ses affectations apparaissent dans l'export de paie, l'alerte DPAE et le contrôle du repos de 11 h (onglet Staff). Aucune fiche prestataire n'est créée.</p>}
          <Field label="Tarif journalier (€)"><Input type="number" min="0" value={f.day_rate} onChange={set("day_rate")} /></Field>
          <Field label="Compétences (séparées par des virgules)" className="col-span-2"><Input defaultValue={f.skills.join(", ")} key={`sk-${open}`} onBlur={(e) => setF({ ...f, skills: e.target.value.split(",").map((s) => s.trim()).filter(Boolean) })} data-testid="member-skills-input" /></Field>
          <Field label="Couleur planning"><Input type="color" value={f.color} onChange={set("color")} className="h-10 w-20 p-1" /></Field>
          <label className="flex items-center gap-2 self-end pb-2 text-sm"><Switch checked={f.active} onCheckedChange={set("active")} />Actif</label>
          {!member && <label className="col-span-2 flex items-center gap-2 text-sm"><input type="checkbox" checked={invite} onChange={(e) => setInvite(e.target.checked)} data-testid="member-send-invite" />Envoyer l'invitation maintenant (e-mail avec un lien valable 7 jours)</label>}
          {member && <div className="col-span-2"><MemberAccess m={member} write onChanged={onSaved} /></div>}
          <p className="col-span-2 text-xs text-muted-foreground">{linked ? "Ce membre a un compte : son rôle se gère dans Paramètres › Membres." : "Aucun e-mail ne part tant que vous n'envoyez pas l'invitation. À sa première connexion avec cet e-mail, cette personne rejoint votre entreprise avec ce rôle."}</p>
          <div className="col-span-2">
            <div className="mb-2 flex items-center justify-between"><span className="text-xs font-medium text-muted-foreground">Indisponibilités</span><Button type="button" size="sm" variant="outline" onClick={() => setF({ ...f, unavailabilities: [...un, { start: "", end: "", reason: "" }] })}><Plus className="mr-1 h-3.5 w-3.5" />Ajouter</Button></div>
            {un.map((u, i) => (
              <div key={i} className="mb-2 flex gap-2">
                <Input type="date" value={u.start} onChange={(e) => setF({ ...f, unavailabilities: un.map((x, j) => (j === i ? { ...x, start: e.target.value } : x)) })} />
                <Input type="date" value={u.end} onChange={(e) => setF({ ...f, unavailabilities: un.map((x, j) => (j === i ? { ...x, end: e.target.value } : x)) })} />
                <Input placeholder="Motif" value={u.reason} onChange={(e) => setF({ ...f, unavailabilities: un.map((x, j) => (j === i ? { ...x, reason: e.target.value } : x)) })} />
                <Button type="button" size="icon" variant="ghost" onClick={() => setF({ ...f, unavailabilities: un.filter((_, j) => j !== i) })}><Trash2 className="h-4 w-4" /></Button>
              </div>
            ))}
          </div>
          <DialogFooter className="col-span-2"><Button data-testid="member-form-submit">Enregistrer</Button></DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function Missions({ member, onOpenChange }) {
  const [rows, setRows] = useState(null);
  useEffect(() => { setRows(null); if (member) api.get(`/team/${member.id}/missions`).then((r) => setRows(r.data)); }, [member]);
  return (
    <Sheet open={!!member} onOpenChange={onOpenChange}>
      <SheetContent className="w-full overflow-y-auto sm:max-w-md">
        <SheetHeader><SheetTitle className="font-display text-2xl font-medium">Missions · {member?.name}</SheetTitle></SheetHeader>
        <div className="mt-4 space-y-2" data-testid="missions-sheet">
          {rows?.length === 0 && <div className="text-sm text-muted-foreground">Aucune mission.</div>}
          {rows?.map((m) => <Link key={m.id} to={`/evenements/${m.id}`} className="block rounded-xl border border-border p-3 hover:bg-secondary/50"><div className="flex justify-between"><span className="text-sm font-medium">{m.title}</span><StatusBadge status={m.status} /></div><div className="text-xs text-muted-foreground">{fmtDT(m.start)} · {m.role}</div></Link>)}
        </div>
      </SheetContent>
    </Sheet>
  );
}

export default function Team() {
  const { can, me } = useMe();
  const write = can("team:write");
  const [rows, setRows] = useState(null);
  const [edit, setEdit] = useState(null);
  const [missions, setMissions] = useState(null);
  const load = () => api.get("/team").then((r) => setRows(r.data));
  useEffect(() => { load(); }, []);
  const roleLabel = (r) => me.roles.find((x) => x.id === r)?.label || r;
  return (
    <div>
      <PageHeader eyebrow="Administratif" title="Équipe" subtitle="Membres, compétences, disponibilités et missions affectées."
        actions={write && <Button onClick={() => setEdit({})} data-testid="new-member-button"><Plus className="mr-1.5 h-4 w-4" />Membre</Button>} />
      {!rows ? <Loading /> : (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3" data-testid="team-grid">
          {rows.map((m) => (
            <div key={m.id} className={`card-soft p-5 hover-lift ${m.active ? "" : "opacity-60"}`} data-testid={`member-card-${m.id}`}>
              <div className="flex items-center gap-3">
                <span className="flex h-11 w-11 items-center justify-center rounded-full font-semibold text-white" style={{ background: m.color }}>{m.name.split(" ").map((x) => x[0]).join("").slice(0, 2)}</span>
                <div className="min-w-0 flex-1"><div className="truncate font-medium">{m.name}</div><div className="text-xs text-muted-foreground">{[m.job, roleLabel(m.access_role)].filter(Boolean).join(" · ")}</div></div>
              </div>
              <MemberAccess m={m} write={write} onChanged={load} />
              <div className="mt-3 flex flex-wrap gap-1">{m.employment_status === "intermittent" && <span className="rounded-md bg-primary/10 px-1.5 py-0.5 text-[11px] font-semibold text-primary" data-testid={`member-intermittent-${m.id}`}>Intermittent (CDDU)</span>}{m.is_driver && <span className="rounded-md bg-secondary px-1.5 py-0.5 text-[11px] font-semibold">Chauffeur</span>}{(m.licences || []).length > 0 && <span className={`rounded-md px-1.5 py-0.5 text-[11px] ${m.licence_valid_until && m.licence_valid_until < new Date().toISOString().slice(0, 10) ? "bg-red-500/15 font-semibold text-red-600" : "bg-secondary"}`} data-testid={`member-licences-${m.id}`}>Permis {m.licences.join(", ")}{m.licence_valid_until ? ` · ${m.licence_valid_until}` : ""}</span>}{m.skills.map((s) => <span key={s} className="rounded-md bg-secondary px-1.5 py-0.5 text-[11px]">{s}</span>)}</div>
              {m.unavailabilities?.length > 0 && <div className="mt-2 text-xs text-amber-700">Indisponible : {m.unavailabilities.map((u) => `${u.start} → ${u.end}`).join(", ")}</div>}
              <div className="mt-4 flex items-center gap-2">
                <Button size="sm" variant="outline" onClick={() => setMissions(m)} data-testid={`member-missions-${m.id}`}><CalendarCheck2 className="mr-1 h-3.5 w-3.5" />Missions</Button>
                {can("users:manage") && <Link className="text-xs underline" to="/parametres?tab=membres" data-testid={`member-manage-link-${m.id}`}>Accès</Link>}{write && <Button size="sm" variant="ghost" onClick={() => setEdit(m)} data-testid={`edit-member-${m.id}`}><Pencil className="mr-1 h-3.5 w-3.5" />Modifier</Button>}
                {m.day_rate > 0 && <span className="ml-auto text-xs text-muted-foreground">{fmtEur(m.day_rate)}/j</span>}
              </div>
            </div>
          ))}
        </div>
      )}
      <MemberDialog open={!!edit} onOpenChange={(o) => !o && setEdit(null)} member={edit?.id ? edit : null} onSaved={load} />
      <Missions member={missions} onOpenChange={(o) => !o && setMissions(null)} />
    </div>
  );
}

import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Switch } from "@/components/ui/switch";
import { Field } from "@/components/common";
import { TranslateButton, langLabel } from "@/lib/i18n";
import { api, errMsg, downloadPdf } from "@/lib/api";
import { fmtDate } from "@/lib/constants";

const STATUS = { invited: "Invité", active: "Actif", suspended: "Suspendu" };
const TPL = { invitation: "Invitation", module_open: "Nouveau module ouvert", music_reminder: "Rappel musique", new_message: "Nouveau message", new_document: "Nouveau document", alert: "Alerte", access_end: "Fin d'accès" };
const ok = (m) => () => toast.success(m);
const ko = (e) => toast.error(errMsg(e));

function Users() {
  const [d, setD] = useState(null);
  const load = useCallback(() => api.get("/portal-users").then((r) => setD(r.data)).catch(ko), []);
  useEffect(() => { load(); }, [load]);
  if (!d) return null;
  const act = (u, a, m) => api.post(`/portal-users/${u.user_id}/${a}`).then((r) => { r.data?.link ? window.prompt("E-mail non envoyé. Lien à transmettre :", r.data.link) : toast.success(m); load(); }).catch(ko);
  return (
    <div data-testid="users-tab">
      {d.denied_alert > 0 && <div className="mb-3 rounded-xl bg-red-500/10 p-3 text-sm font-semibold text-red-600" data-testid="denied-alert">Alerte : {d.denied_alert} accès refusés au cours des 10 dernières minutes. Consultez le journal.</div>}
      <div className="card-soft divide-y divide-border">{d.users.map((u) => (
        <div key={u.user_id} className="flex flex-wrap items-center gap-3 p-3 text-sm" data-testid={`user-row-${u.user_id}`}>
          <div className="min-w-0 flex-1"><b>{u.name}</b><div className="text-xs text-muted-foreground">{u.email} · {langLabel(u.language)} · dernière connexion : {u.last_login_at ? fmtDate(u.last_login_at) : "jamais"}</div></div>
          <span className="rounded-full bg-secondary px-2.5 py-0.5 text-xs font-semibold">{u.role_label}</span><span className="text-xs">{STATUS[u.status] || u.status}</span>
          {!u.portal && <span className="text-xs text-muted-foreground">2FA : {u.two_factor == null ? "non vérifiée" : u.two_factor ? "activée" : "absente"}</span>}
          {u.portal && <><Button size="sm" variant="ghost" onClick={() => act(u, "resend", "Invitation renvoyée")}>Renvoyer</Button>
            {u.status === "suspended" ? <Button size="sm" variant="ghost" onClick={() => act(u, "reactivate", "Réactivé")}>Réactiver</Button> : <Button size="sm" variant="ghost" onClick={() => act(u, "suspend", "Suspendu")}>Suspendre</Button>}
            <Button size="sm" variant="ghost" onClick={() => act(u, "revoke", "Sessions révoquées")} data-testid={`user-revoke-${u.user_id}`}>Révoquer les sessions</Button>
            <a className="text-xs font-semibold underline" href={`/apercu/${u.user_id}`} target="_blank" rel="noreferrer" data-testid={`user-view-as-${u.user_id}`}>Voir comme</a></>}
        </div>))}</div>
    </div>
  );
}

function Modules() {
  const [d, setD] = useState(null);
  useEffect(() => { api.get("/portal-modules").then((r) => setD(r.data)).catch(ko); }, []);
  if (!d) return null;
  const up = (i, k, v) => setD({ ...d, modules: d.modules.map((m, j) => (j === i ? { ...m, [k]: v } : m)) });
  const move = (i, n) => { const a = [...d.modules]; const [x] = a.splice(i, 1); a.splice(i + n, 0, x); setD({ ...d, modules: a }); };
  const def = (type, key, k, v) => setD({ ...d, defaults: { ...d.defaults, [type]: { ...d.defaults[type], [key]: { client_visible: false, lock_offset_days: 0, ...(d.defaults[type] || {})[key], [k]: v } } } });
  return (
    <div data-testid="portal-modules-admin">
      <div className="card-soft divide-y divide-border">{d.modules.map((m, i) => (
        <div key={m.key} className="flex flex-wrap items-center gap-2 p-3 text-sm" data-testid={`module-row-${m.key}`}>
          <div className="flex flex-col"><button disabled={!i} onClick={() => move(i, -1)} aria-label="Monter">▲</button><button disabled={i === d.modules.length - 1} onClick={() => move(i, 1)} aria-label="Descendre">▼</button></div>
          <Input className="h-9 w-48" value={m.label} onChange={(e) => up(i, "label", e.target.value)} data-testid={`module-label-${m.key}`} /><Input className="h-9 w-48" placeholder="English" value={m.label_en} onChange={(e) => up(i, "label_en", e.target.value)} />
          <label className="flex items-center gap-2"><Switch disabled={m.key === "home"} checked={m.active} onCheckedChange={(v) => up(i, "active", v)} data-testid={`module-active-${m.key}`} />Actif</label>
          <label className="flex items-center gap-2"><Switch checked={m.notify !== false} onCheckedChange={(v) => up(i, "notify", v)} />E-mail à l'ouverture</label>
          {!d.built.includes(m.key) && <span className="text-xs text-muted-foreground">à venir</span>}
        </div>))}</div>
      <h3 className="mb-2 mt-6 font-semibold">Réglages par défaut selon le type d'événement</h3>
      {Object.keys(d.defaults).map((type) => <div key={type} className="card-soft mb-3 p-3 text-sm"><b>{type === "*" ? "Tous les autres types" : type}</b>
        <div className="mt-2 flex flex-wrap gap-4">{d.modules.filter((m) => m.key !== "home").map((m) => { const x = (d.defaults[type] || {})[m.key] || {}; return <div key={m.key} className="flex items-center gap-2"><Switch checked={!!x.client_visible} onCheckedChange={(v) => def(type, m.key, "client_visible", v)} />{m.label}<Input type="number" min="0" title="Verrouillage : jours avant l'événement" className="h-8 w-16" value={x.lock_offset_days || 0} onChange={(e) => def(type, m.key, "lock_offset_days", Number(e.target.value) || 0)} /><span className="text-xs text-muted-foreground">j avant</span></div>; })}</div></div>)}
      <Button onClick={() => api.put("/portal-modules", { modules: d.modules, defaults: d.defaults }).then(ok("Modules enregistrés")).catch(ko)} data-testid="modules-save">Enregistrer</Button>
    </div>
  );
}

function Journal() {
  const [d, setD] = useState(null);
  const [f, setF] = useState({ action: "", q: "" });
  useEffect(() => { api.get("/audit-logs", { params: f }).then((r) => setD(r.data)).catch(ko); }, [f]);
  if (!d) return null;
  return (
    <div data-testid="audit-tab">
      <div className="mb-3 flex flex-wrap gap-2"><select className="h-10 rounded-lg border border-border bg-background px-3 text-sm" value={f.action} onChange={(e) => setF({ ...f, action: e.target.value })} data-testid="audit-action"><option value="">Toutes les actions</option>{d.actions.map((a) => <option key={a}>{a}</option>)}</select>
        <Input className="max-w-xs" placeholder="Rechercher…" value={f.q} onChange={(e) => setF({ ...f, q: e.target.value })} data-testid="audit-search" /><Button variant="outline" onClick={() => downloadPdf("/audit-logs?format=csv", "journal.csv")} data-testid="audit-export">Export CSV</Button></div>
      <div className="card-soft divide-y divide-border text-sm">{d.rows.map((r) => <div key={r.id} className="flex flex-wrap gap-3 p-2.5"><span className="w-40 text-xs text-muted-foreground">{new Date(r.at).toLocaleString("fr-FR")}</span><b className="w-40 truncate">{r.actor_name}</b><span className="w-40">{r.action}</span><span className="min-w-0 flex-1 truncate">{r.target} {r.detail}</span></div>)}</div>
      <p className="mt-2 text-xs text-muted-foreground">Journal non modifiable, conservé 12 mois.</p>
    </div>
  );
}

function Templates() {
  const [d, setD] = useState(null);
  const [key, setKey] = useState("invitation");
  useEffect(() => { api.get("/email-templates").then((r) => setD(r.data)).catch(ko); }, []);
  if (!d) return null;
  const get = (lg) => d.templates.find((t) => t.key === key && t.language === lg);
  const up = (lg, k, v) => setD({ ...d, templates: d.templates.map((t) => (t.key === key && t.language === lg ? { ...t, [k]: v } : t)) });
  return (
    <div data-testid="templates-tab">
      <div className="mb-3 flex flex-wrap items-center gap-2"><select className="h-10 rounded-lg border border-border bg-background px-3 text-sm" value={key} onChange={(e) => setKey(e.target.value)} data-testid="template-key">{Object.entries(TPL).map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select>
        <TranslateButton label="Générer la traduction (IA)" testid="template-translate" context="E-mail transactionnel." texts={{ subject: get("fr").subject, body_html: get("fr").body_html }} onDone={(r) => setD((cur) => ({ ...cur, templates: cur.templates.map((t) => (t.key === key && t.language === "en" ? { ...t, ...r } : t)) }))} /></div>
      <p className="mb-3 text-xs text-muted-foreground">Variables : {d.variables.map((v) => `{${v}}`).join(" ")}</p>
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">{["fr", "en"].map((lg) => { const t = get(lg); return <div key={lg} className="card-soft p-4"><b>{lg === "fr" ? "Français" : "English"}</b>{!t.subject.trim() && <span className="ml-2 text-xs text-amber-700">Version manquante</span>}
        <Input className="mt-2" value={t.subject} onChange={(e) => up(lg, "subject", e.target.value)} data-testid={`template-subject-${lg}`} /><Textarea className="mt-2" rows={9} value={t.body_html} onChange={(e) => up(lg, "body_html", e.target.value)} data-testid={`template-body-${lg}`} />
        <Button size="sm" className="mt-2" onClick={() => api.put("/email-templates", { key, language: lg, subject: t.subject, body_html: t.body_html }).then(ok("Modèle enregistré")).catch(ko)} data-testid={`template-save-${lg}`}>Enregistrer</Button></div>; })}</div>
    </div>
  );
}

function Settings() {
  const [f, setF] = useState(null);
  const [req, setReq] = useState(null);
  const load = useCallback(() => { api.get("/portal-settings").then((r) => setF(r.data)).catch(ko); api.get("/portal-requests").then((r) => setReq(r.data)).catch(ko); }, []);
  useEffect(() => { load(); }, [load]);
  if (!f || !req) return null;
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value });
  return (
    <div className="space-y-6" data-testid="portal-settings-tab">
      <div className="card-soft grid grid-cols-1 gap-4 p-4 sm:grid-cols-3">
        <Field label="Lecture seule après l'événement (jours)"><Input type="number" value={f.read_only_days} onChange={set("read_only_days")} data-testid="settings-read-only" /></Field>
        <Field label="Désactivation après l'événement (jours)"><Input type="number" value={f.disable_days} onChange={set("disable_days")} /></Field>
        <Field label="Contacts sur place visibles (jours avant)"><Input type="number" value={f.onsite_days} onChange={set("onsite_days")} /></Field>
        <div className="sm:col-span-3"><TranslateButton testid="legal-translate" context="Textes juridiques." texts={{ privacy_en: f.privacy, legal_en: f.legal }} onDone={(r) => setF((c) => ({ ...c, ...r }))} /></div>
        {[["privacy", "Politique de confidentialité"], ["privacy_en", "Privacy policy"], ["legal", "Mentions légales"], ["legal_en", "Legal notice"]].map(([k, l]) => <Field key={k} label={l} className="sm:col-span-3"><Textarea rows={5} value={f[k]} onChange={set(k)} data-testid={`settings-${k}`} /></Field>)}
        <div className="sm:col-span-3 flex items-center gap-4"><Button onClick={() => api.put("/portal-settings", { ...f, read_only_days: Number(f.read_only_days), disable_days: Number(f.disable_days), onsite_days: Number(f.onsite_days) }).then(ok("Réglages enregistrés")).catch(ko)} data-testid="settings-save">Enregistrer</Button>
          <a className="text-sm underline" href={`/legal/${f.org_id}/privacy`} target="_blank" rel="noreferrer">Voir la page publique</a></div>
      </div>
      <div className="card-soft p-4 text-sm" data-testid="profile-changes"><h3 className="mb-2 font-semibold">Modifications de conditions à valider (prestataires)</h3>{!req.changes.length && <p className="text-muted-foreground">Aucune demande.</p>}
        {req.changes.map((c) => <div key={c.id} className="flex flex-wrap items-center gap-3 border-b border-border py-2 last:border-0"><b>{c.provider_name}</b><span className="flex-1">{Object.entries(c.changes).map(([k, v]) => `${k} : ${c.previous?.[k] ?? "—"} → ${v}`).join(" · ")}</span>
          {c.status === "pending" ? <><Button size="sm" onClick={() => api.post(`/profile-changes/${c.id}/approve`).then(load).catch(ko)} data-testid={`change-approve-${c.id}`}>Valider</Button><Button size="sm" variant="ghost" onClick={() => api.post(`/profile-changes/${c.id}/reject`).then(load).catch(ko)}>Refuser</Button></> : <span className="text-xs">{c.status === "approved" ? "Validée" : "Refusée"} par {c.reviewed_by}</span>}</div>)}</div>
      <div className="card-soft p-4 text-sm" data-testid="gdpr-requests"><h3 className="mb-2 font-semibold">Demandes de suppression (RGPD)</h3>{!req.gdpr.length && <p className="text-muted-foreground">Aucune demande.</p>}
        {req.gdpr.map((g) => <div key={g.id} className="flex items-center gap-3 border-b border-border py-2 last:border-0"><span className="flex-1">{g.name} {g.email} · {fmtDate(g.created_at)}</span>{g.status === "pending" ? <Button size="sm" variant="outline" onClick={() => window.confirm("Anonymiser ce contact ? Les devis et factures sont conservés. Action irréversible.") && api.post(`/gdpr-requests/${g.id}/anonymize`).then(load).catch(ko)}>Anonymiser</Button> : <span className="text-xs">Traitée</span>}</div>)}</div>
    </div>
  );
}

export { Users as PortalUsers, Modules as PortalModules, Journal, Templates, Settings };

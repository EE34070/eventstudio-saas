import { useEffect, useState } from "react";
import { LabelManager } from "@/components/messaging/Labels";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Switch } from "@/components/ui/switch";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog";
import { Field, Loading } from "@/components/common";
import { api, errMsg } from "@/lib/api";
import { EVENT_TYPES, fmtDT } from "@/lib/constants";
import { useMe } from "@/context/MeContext";

export const SettingsDialog = ({ open, onOpenChange, status, onChanged }) => {
  const { can } = useMe();
  const admin = can("org:write");
  const [f, setF] = useState(status.settings);
  const [busy, setBusy] = useState(false);
  useEffect(() => { if (open) setF(status.settings); }, [open]); // eslint-disable-line react-hooks/exhaustive-deps
  const acc = status.account;
  const connected = acc?.status === "connected";
  const run = async (fn, ok) => {
    setBusy(true);
    try { await fn(); if (ok) toast.success(ok); onChanged(); } catch (e) { toast.error(errMsg(e)); }
    setBusy(false);
  };
  const connect = () => run(async () => {
    const r = await api.get("/messaging/gmail/connect", { params: { return_to: window.location.origin } });
    window.location.assign(r.data.url);
  });
  const disconnect = () => window.confirm("Déconnecter la boîte Gmail ? Les conversations déjà importées restent consultables.") && run(() => api.delete("/messaging/account"), "Boîte déconnectée");
  const purge = () => window.confirm(`Effacer définitivement ${status.purgeable} conversation(s) en corbeille depuis plus de ${status.trash_days} jours ? Cette action est irréversible dans l'application. Dans Gmail, ces e-mails sont déjà à la corbeille.`)
    && run(() => api.post("/messaging/trash/purge"), "Corbeille nettoyée");
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[92vh] max-w-xl overflow-y-auto" data-testid="messaging-settings-dialog">
        <DialogHeader><DialogTitle className="font-display text-2xl font-medium">Réglages de la messagerie</DialogTitle></DialogHeader>
        <div className="space-y-5 text-sm">
          <div className="rounded-2xl border border-border p-4" data-testid="settings-account">
            <div className="font-semibold">Boîte Gmail partagée</div>
            {acc ? <p className="mt-1 text-muted-foreground" data-testid="settings-account-email">{acc.email} — {connected ? "connectée" : "déconnectée"}{acc.last_sync_at ? ` · dernière synchronisation ${fmtDT(new Date(acc.last_sync_at).toLocaleString("sv-SE").replace(" ", "T"))}` : ""}</p>
              : <p className="mt-1 text-muted-foreground">Aucune boîte connectée.</p>}
            {connected && <p className="mt-1 text-xs text-muted-foreground" data-testid="settings-watch-state">{acc.watch_error ? `Notifications instantanées indisponibles (${acc.watch_error.slice(0, 140)}) : synchronisation toutes les 5 minutes.` : acc.watch_expiration ? "Notifications instantanées actives." : "Synchronisation toutes les 5 minutes."}</p>}
            {acc && status.progress && (
              <div className="mt-3 rounded-xl bg-secondary/60 p-3 text-xs" data-testid="settings-sync-progress">
                <div className="font-semibold">{{ running: "Import en cours", paused: "Import en pause (quota Gmail), reprise automatique", error: "Import interrompu, nouvel essai automatique", done: "Import terminé" }[acc.import?.status] || "Import"}</div>
                <div className="mt-1" data-testid="settings-sync-counts">{status.progress.imported} message(s) importé(s) · {status.progress.pending} en attente · {status.progress.failed} en échec</div>
                {acc.last_error && <div className="mt-1 text-red-600" data-testid="settings-sync-error">{acc.last_error}</div>}
                {status.progress.reasons.map((r) => <div key={r.reason} className="mt-1 text-muted-foreground" data-testid={`settings-sync-reason-${r.reason}`}>{r.count} × {r.label} — Google : {r.message}</div>)}
                {status.progress.failed > 0 && <div className="mt-1 text-muted-foreground">Les messages en échec sont réessayés à chaque synchronisation (8 essais au plus).</div>}
              </div>
            )}
            {!status.configured.google && <p className="mt-2 text-xs text-red-600">Identifiants Google absents du serveur (GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET).</p>}
            {admin && <p className="mt-2 break-all text-xs text-muted-foreground">URI de redirection à autoriser dans le client OAuth Google : <b className="text-foreground" data-testid="settings-redirect-uri">{status.redirect_uri}</b></p>}
            {admin && (
              <div className="mt-3 flex flex-wrap gap-2">
                <Button size="sm" onClick={connect} disabled={busy || !status.configured.google} data-testid="settings-connect-button">{connected ? "Changer de boîte" : acc ? "Reconnecter Gmail" : "Connecter Gmail"}</Button>
                {connected && <Button size="sm" variant="outline" onClick={disconnect} disabled={busy} data-testid="settings-disconnect-button">Déconnecter</Button>}
              </div>
            )}
          </div>
          <div className="flex items-center gap-4">
            <div className="min-w-0 flex-1"><div className="font-semibold">Classement automatique par l'IA</div><div className="text-muted-foreground">Chaque e-mail reçu est classé et résumé{status.configured.ai ? "." : " (clé Anthropic absente : inactif)."}</div></div>
            <Switch checked={f.auto_classify} disabled={!admin} onCheckedChange={(v) => setF({ ...f, auto_classify: v })} data-testid="settings-auto-classify-switch" />
          </div>
          <Field label="Signature ajoutée aux messages envoyés"><Textarea rows={3} value={f.signature} disabled={!admin} onChange={(e) => setF({ ...f, signature: e.target.value })} data-testid="settings-signature-input" /></Field>
          <Field label="Mettre en corbeille les conversations sans activité depuis (mois, 0 = jamais)"><Input type="number" min={0} max={120} value={f.retention_months} disabled={!admin} onChange={(e) => setF({ ...f, retention_months: Number(e.target.value) || 0 })} data-testid="settings-retention-input" /></Field>
          {connected && <div className="rounded-2xl border border-border p-4" data-testid="settings-full-import">
            <div className="font-semibold">Boîte complète</div>
            <p className="mt-1 text-muted-foreground">{status.full_import ? "L'import des 12 derniers mois a été lancé : tous les fils sont repris, sauf Spam et Corbeille." : "Aujourd'hui seuls les 90 derniers jours sont importés. L'import complet reprend tous les fils des 12 derniers mois (hors Spam et Corbeille), en tâche de fond."}</p>
            {admin && <Button size="sm" variant="outline" className="mt-3" disabled={busy || acc.import?.status === "running"} onClick={() => window.confirm("Importer tous les e-mails des 12 derniers mois ? L'import tourne en arrière-plan et peut durer plusieurs dizaines de minutes.") && run(() => api.post("/messaging/import-full"), "Import des 12 derniers mois lancé")} data-testid="settings-import-full-button">Importer les 12 derniers mois</Button>}
          </div>}
          {connected && <LabelManager status={status} admin={admin} onChanged={onChanged} />}
          <div className="rounded-2xl border border-border p-4" data-testid="settings-trash">
            <div className="font-semibold">Corbeille</div>
            <p className="mt-1 text-muted-foreground">{status.trash} conversation(s) en corbeille, restaurables pendant {status.trash_days} jours, puis effacées définitivement chaque nuit à 3 h. La corbeille agit aussi dans Gmail : mettre une conversation à la corbeille ici la place dans la corbeille Gmail, la restaurer l'en ressort.</p>
            {admin && <Button size="sm" variant="outline" className="mt-3" disabled={busy || !status.purgeable} onClick={purge} data-testid="settings-purge-button">Effacer maintenant les conversations échues ({status.purgeable})</Button>}
          </div>
        </div>
        {admin && <DialogFooter><Button disabled={busy} onClick={() => run(() => api.put("/messaging/settings", f), "Réglages enregistrés")} data-testid="settings-save-button">Enregistrer</Button></DialogFooter>}
      </DialogContent>
    </Dialog>
  );
};

export const ComposeDialog = ({ open, onOpenChange, onSent, preset }) => {
  const [f, setF] = useState({ to: "", subject: "", text: "" });
  const [busy, setBusy] = useState(false);
  useEffect(() => { if (open) setF({ to: "", subject: "", text: "", ...preset }); }, [open]); // eslint-disable-line react-hooks/exhaustive-deps
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value });
  const submit = async (e) => {
    e.preventDefault();
    setBusy(true);
    try { const r = await api.post("/messaging/send", f); toast.success("Message envoyé"); onOpenChange(false); onSent(r.data.id); } catch (err) { toast.error(errMsg(err)); }
    setBusy(false);
  };
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-xl" data-testid="compose-dialog">
        <DialogHeader><DialogTitle className="font-display text-2xl font-medium">Nouveau message</DialogTitle></DialogHeader>
        <form onSubmit={submit} className="space-y-4">
          <Field label="Destinataire"><Input type="email" required value={f.to} onChange={set("to")} data-testid="compose-to-input" /></Field>
          <Field label="Objet"><Input required value={f.subject} onChange={set("subject")} data-testid="compose-subject-input" /></Field>
          <Field label="Message"><Textarea rows={8} required value={f.text} onChange={set("text")} data-testid="compose-text-input" /></Field>
          <DialogFooter><Button type="submit" disabled={busy} data-testid="compose-send-button">{busy ? "Envoi…" : "Envoyer"}</Button></DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
};

export const EventFromDialog = ({ open, onOpenChange, convId, onCreated }) => {
  const nav = useNavigate();
  const [f, setF] = useState(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    if (!open) return;
    setF(null);
    api.post(`/messaging/conversations/${convId}/event-draft`).then((r) => setF(r.data)).catch((e) => { toast.error(errMsg(e)); onOpenChange(false); });
  }, [open, convId]); // eslint-disable-line react-hooks/exhaustive-deps
  const set = (k) => (e) => setF({ ...f, [k]: e?.target ? e.target.value : e });
  const submit = async (e) => {
    e.preventDefault();
    setBusy(true);
    try {
      const r = await api.post(`/messaging/conversations/${convId}/event`, { title: f.title, type: f.type, start: f.start, end: f.end, guests: Number(f.guests) || 0 });
      toast.success(`Événement ${r.data.code} créé au statut Demande`);
      onOpenChange(false); onCreated(); nav(`/evenements/${r.data.id}`);
    } catch (err) { toast.error(errMsg(err)); }
    setBusy(false);
  };
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-xl" data-testid="event-from-dialog">
        <DialogHeader><DialogTitle className="font-display text-2xl font-medium">Créer l'événement</DialogTitle></DialogHeader>
        {!f ? <Loading /> : (
          <form onSubmit={submit} className="grid grid-cols-2 gap-4">
            <p className="col-span-2 text-sm text-muted-foreground" data-testid="event-from-hint">{f.ai ? "Champs préremplis par l'IA à partir de l'e-mail : vérifiez-les, en particulier la date." : "Renseignez la date de l'événement."} L'événement sera créé au statut « Demande », lié au contact, avec le texte de l'e-mail en note.</p>
            <Field label="Titre" className="col-span-2"><Input required value={f.title} onChange={set("title")} data-testid="event-from-title" /></Field>
            <Field label="Type"><Select value={f.type} onValueChange={set("type")}><SelectTrigger data-testid="event-from-type"><SelectValue /></SelectTrigger><SelectContent>{EVENT_TYPES.map((t) => <SelectItem key={t} value={t}>{t}</SelectItem>)}</SelectContent></Select></Field>
            <Field label="Invités"><Input type="number" min={0} value={f.guests} onChange={set("guests")} data-testid="event-from-guests" /></Field>
            <Field label="Début"><Input type="datetime-local" required value={f.start} onChange={set("start")} data-testid="event-from-start" /></Field>
            <Field label="Fin"><Input type="datetime-local" required value={f.end} onChange={set("end")} data-testid="event-from-end" /></Field>
            <DialogFooter className="col-span-2"><Button type="submit" disabled={busy} data-testid="event-from-submit">{busy ? "Création…" : "Créer l'événement"}</Button></DialogFooter>
          </form>
        )}
      </DialogContent>
    </Dialog>
  );
};

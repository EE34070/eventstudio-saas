import { useCallback, useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { toast } from "sonner";
import { Mail, PenLine, RefreshCw, Settings } from "lucide-react";
import { Button } from "@/components/ui/button";
import { PageHeader, Loading, EmptyState } from "@/components/common";
import { api, errMsg } from "@/lib/api";
import { useMe } from "@/context/MeContext";
import { ConversationList } from "@/components/messaging/ConversationList";
import { Thread } from "@/components/messaging/Thread";
import { ContextPanel } from "@/components/messaging/ContextPanel";
import { SettingsDialog, ComposeDialog } from "@/components/messaging/MessagingDialogs";

const OAUTH = {
  ok: ["success", "Boîte Gmail connectée : l'import des 90 derniers jours démarre."],
  refus: ["error", "Connexion annulée : l'accès à Gmail n'a pas été accordé."],
  droits: ["error", "Google n'a pas accordé tous les droits demandés. Recommencez en cochant l'accès à Gmail."],
  deja: ["error", "Cette boîte est déjà connectée à une autre société."],
  erreur: ["error", "Google a refusé la connexion. Vérifiez l'URI de redirection du client OAuth."],
};

export default function Messagerie() {
  const { can } = useMe();
  const write = can("messages:write");
  const [params, setParams] = useSearchParams();
  const [status, setStatus] = useState(null);
  const [filters, setFilters] = useState({ box: "inbox", q: "", category: "", unread: false, gcat: "", label_id: "", unlinked: false });
  const [rows, setRows] = useState(null);
  const [conv, setConv] = useState(null);
  const [settings, setSettings] = useState(false);
  const [compose, setCompose] = useState(params.get("compose") === "1");
  const preset = params.get("compose") === "1" ? { to: params.get("to") || "", subject: params.get("subject") || "", text: params.get("text") || "" } : null;
  const selected = params.get("c");

  const loadStatus = useCallback(() => api.get("/messaging/status").then((r) => setStatus(r.data)).catch((e) => toast.error(errMsg(e))), []);
  const loadList = useCallback(() => api.get("/messaging/conversations", { params: { ...filters, unread: filters.unread || undefined, unlinked: filters.unlinked || undefined, limit: 100 } })
    .then((r) => setRows(r.data)).catch((e) => toast.error(errMsg(e))), [filters]);
  const loadConv = useCallback(() => (selected
    ? api.get(`/messaging/conversations/${selected}`).then((r) => setConv(r.data)).catch(() => setConv(null))
    : Promise.resolve(setConv(null))), [selected]);
  const refresh = useCallback(() => { loadStatus(); loadList(); loadConv(); }, [loadStatus, loadList, loadConv]);

  useEffect(() => { loadStatus(); }, [loadStatus]);
  useEffect(() => { const t = setTimeout(loadList, filters.q ? 300 : 0); return () => clearTimeout(t); }, [loadList, filters.q]);
  useEffect(() => { setConv(null); loadConv(); }, [loadConv]);
  useEffect(() => {
    const res = OAUTH[params.get("gmail")];
    if (!res) return;
    toast[res[0]](res[1]);
    params.delete("gmail");
    setParams(params, { replace: true });
  }, [params, setParams]);
  const importing = status?.account?.status === "connected" && ["running", "paused"].includes(status.account.import?.status);
  useEffect(() => {
    const t = setInterval(() => { loadStatus(); loadList(); }, importing ? 4000 : 30000);
    return () => clearInterval(t);
  }, [importing, loadStatus, loadList]);

  const select = (id) => { id ? params.set("c", id) : params.delete("c"); setParams(params); };
  const sync = async () => {
    try { await api.post("/messaging/sync"); toast.success("Synchronisation lancée"); setTimeout(refresh, 4000); } catch (e) { toast.error(errMsg(e)); }
  };

  if (!status) return <Loading />;
  const acc = status.account;
  const connected = acc?.status === "connected";
  return (
    <div data-testid="messaging-page">
      <PageHeader title="Messagerie" subtitle={acc ? `${acc.email} — ${status.unread} conversation(s) non lue(s).` : "Connectez la boîte Gmail partagée de la société."}
        actions={<>
          {connected && <Button variant="outline" size="sm" onClick={sync} data-testid="messaging-sync-button"><RefreshCw />Synchroniser</Button>}
          <Button variant="outline" size="sm" onClick={() => setSettings(true)} data-testid="messaging-settings-button"><Settings />Réglages</Button>
          {connected && write && <Button size="sm" onClick={() => setCompose(true)} data-testid="messaging-compose-button"><PenLine />Nouveau message</Button>}
        </>} />
      {acc && !connected && <div className="mb-4 rounded-2xl border border-red-500/30 bg-red-500/5 p-4 text-sm" data-testid="messaging-account-alert">{acc.last_error || "La boîte Gmail est déconnectée."} Ouvrez les réglages pour la reconnecter.</div>}
      {connected && acc.last_error && <div className="mb-4 rounded-2xl border border-amber-500/30 bg-amber-500/5 p-4 text-sm" data-testid="messaging-sync-alert">{acc.last_error}</div>}
      {importing && <div className="mb-4 rounded-2xl border border-border p-4 text-sm" data-testid="messaging-import-progress">Import des {status.import_days} derniers jours {acc.import.status === "paused" ? "en pause (quota Gmail), reprise automatique" : "en cours"} : {status.progress.imported} importés, {status.progress.pending} en attente, {status.progress.failed} en échec.</div>}
      {!acc ? (
        <EmptyState icon={Mail} title="Aucune boîte connectée" text="Un administrateur connecte la boîte partagée (ex. contact@) ; les e-mails des 90 derniers jours sont alors importés et rattachés aux contacts."
          action={can("org:write") && <Button onClick={() => setSettings(true)} data-testid="messaging-connect-cta">Connecter Gmail</Button>} />
      ) : (
        <div className="grid h-[calc(100vh-250px)] min-h-[520px] grid-cols-1 gap-4 lg:grid-cols-[340px_minmax(0,1fr)] xl:grid-cols-[340px_minmax(0,1fr)_320px]" data-testid="messaging-columns">
          <div className={`min-h-0 ${selected ? "hidden lg:block" : ""}`}>
            <ConversationList rows={rows} filters={filters} setFilters={setFilters} selected={selected} onSelect={select} status={status} write={write} onChanged={refresh} />
          </div>
          <div className={`min-h-0 ${selected ? "" : "hidden lg:block"}`}>
            <Thread conv={conv} selected={selected} status={status} write={write} onBack={() => select(null)} onChanged={refresh} setConv={setConv} />
          </div>
          <div className={`min-h-0 ${selected ? "" : "hidden"} lg:col-span-2 xl:col-span-1 xl:block`}>
            {conv && <ContextPanel conv={conv} status={status} write={write} setConv={setConv} onChanged={refresh} />}
          </div>
        </div>
      )}
      <SettingsDialog open={settings} onOpenChange={setSettings} status={status} onChanged={refresh} />
      <ComposeDialog preset={preset} open={compose} onOpenChange={setCompose} onSent={(id) => { refresh(); select(id); }} />
    </div>
  );
}

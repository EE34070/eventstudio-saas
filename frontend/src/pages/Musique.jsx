import { useEffect, useState } from "react";
import { toast } from "sonner";
import { PageHeader } from "@/components/common";
import Music from "@/portal/Music";
import { makeT } from "@/portal/tr";
import { api, errMsg } from "@/lib/api";
import { fmtDate } from "@/lib/constants";

const FR = makeT("fr-FR");
const STATUS = { none: "Non commencé", draft: "Brouillon", sent: "Envoyé au DJ", validated: "Validé par le DJ" };

export const EventMusic = ({ ev }) => <Music base={`/events/${ev.id}/music`} tr={FR} />;

export default function Musique() {
  const [rows, setRows] = useState(null);
  const [open, setOpen] = useState(null);
  useEffect(() => { if (!open) api.get("/music-plans").then((r) => setRows(r.data)).catch((e) => toast.error(errMsg(e))); }, [open]);
  if (open) return <div className="mx-auto max-w-3xl"><button className="mb-4 text-sm font-semibold underline" onClick={() => setOpen(null)} data-testid="music-back">← Retour à la liste</button><h2 className="mb-4 text-2xl font-bold">{open.title}</h2><Music base={`/events/${open.event_id}/music`} tr={FR} /></div>;
  return (
    <div data-testid="music-plans-page">
      <PageHeader eyebrow="DJ" title="Ma musique" subtitle="Programmation musicale des événements : statut, date limite et avancement." />
      {rows && !rows.length && <p className="text-sm text-muted-foreground">Aucun événement à venir avec le module « Ma musique » visible. Activez-le dans l'onglet « Espace client » d'un événement.</p>}
      <div className="card-soft divide-y divide-border">{(rows || []).map((r) => (
        <button key={r.event_id} onClick={() => setOpen(r)} className="flex w-full flex-wrap items-center gap-3 p-3 text-left text-sm hover:bg-secondary/50" data-testid={`music-plan-row-${r.event_id}`}>
          <div className="min-w-0 flex-1"><b>{r.title}</b><div className="text-xs text-muted-foreground">{fmtDate(r.start)} · date limite : {r.lock_date ? fmtDate(r.lock_date) : "aucune"}{!r.visible && " · masqué au client"}</div></div>
          {r.pending > 0 && <span className="rounded-full bg-amber-500/10 px-2.5 py-0.5 text-xs font-semibold text-amber-700">{r.pending} suggestion(s)</span>}
          <span className="rounded-full bg-secondary px-2.5 py-0.5 text-xs font-semibold">{STATUS[r.status]}</span><span className="w-12 text-right font-semibold">{r.completion} %</span>
        </button>))}</div>
    </div>
  );
}

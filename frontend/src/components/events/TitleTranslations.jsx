import { useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { api, errMsg } from "@/lib/api";

const ko = (e) => toast.error(errMsg(e));

export function TitleTranslations({ base, label }) {
  const [d, setD] = useState(null);
  const [v, setV] = useState({});
  const isEvent = base.startsWith("/events");
  const fill = (data) => { setD(data); setV(Object.fromEntries(data.languages.map((l) => [l.code, l.title]))); };
  const open = () => api.get(`${base}/title-translations`).then((r) => fill(r.data)).catch(ko);
  const save = (lang) => api.put(`${base}/title-translations`, { lang, title: v[lang] || "" }).then((r) => { fill(r.data); toast.success("Titre enregistré"); }).catch(ko);
  const ai = (lang) => api.post(`${base}/title-translations/ai`, { lang }).then((r) => { setV((x) => ({ ...x, [lang]: r.data.title })); toast.success("Brouillon généré : relisez avant d'enregistrer"); }).catch(ko);
  return (<>
    <button type="button" className="mt-1 text-xs underline" onClick={open} data-testid={isEvent ? "event-title-translations" : "quote-title-translations"}>{label}</button>
    {d && <Dialog open onOpenChange={(o) => !o && setD(null)}><DialogContent className="max-w-2xl" data-testid="title-translations-dialog">
      <DialogHeader><DialogTitle>{isEvent ? "Traductions du titre" : "Titre du devis par langue"}</DialogTitle><DialogDescription>Titre français : « {d.title} ». {isEvent ? "Le client voit le titre dans la langue de son devis ; en interne, le titre reste en français." : "Laissez vide pour reprendre le titre de l'événement dans cette langue."}</DialogDescription></DialogHeader>
      <div className="space-y-2">{d.languages.map((l) => (
        <div key={l.code} className="flex flex-wrap items-center gap-2 text-sm" data-testid={`title-row-${l.code}`}><span className="w-36 shrink-0">{l.label} {l.stale && <span className="rounded-full bg-orange-500 px-1.5 text-xs text-white" data-testid={`title-stale-${l.code}`}>à revoir</span>}</span>
          <Input className="h-9 min-w-0 flex-1" placeholder={isEvent ? "— absent" : l.inherited} value={v[l.code] || ""} onChange={(e) => setV({ ...v, [l.code]: e.target.value })} data-testid={`title-input-${l.code}`} />
          {isEvent && <Button type="button" size="sm" variant="outline" onClick={() => ai(l.code)} data-testid={`title-ai-${l.code}`}>IA</Button>}<Button type="button" size="sm" onClick={() => save(l.code)} data-testid={`title-save-${l.code}`}>Enregistrer</Button></div>))}</div>
    </DialogContent></Dialog>}
  </>);
}

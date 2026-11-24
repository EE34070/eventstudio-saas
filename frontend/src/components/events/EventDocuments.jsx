import { useEffect, useState } from "react";
import { toast } from "sonner";
import { Download, FileText, LayoutPanelTop } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Section } from "@/components/common";
import { openFile } from "@/lib/files";
import { api, downloadPdf } from "@/lib/api";

export default function EventDocuments({ ev }) {
  const [docs, setDocs] = useState([]);
  useEffect(() => { api.get(`/events/${ev.id}/documents`).then((r) => setDocs(r.data)).catch(() => {}); }, [ev.id]);
  const zones = ev.venue?.sections || [];
  const known = new Set(zones.map((z) => z.id));
  const groups = [...zones, { id: "", name: "Non affecté" }]
    .map((z) => ({ z, lines: (ev.equipment || []).filter((l) => (z.id ? l.section_id === z.id : !known.has(l.section_id))) }))
    .filter((g) => g.lines.length);
  return (
    <div className="space-y-6">
      <Section title="Plan d'implantation" testid="implantation-section"
        actions={<Button size="sm" onClick={() => downloadPdf(`/events/${ev.id}/implantation/pdf`, `implantation-${ev.code}.pdf`).catch(() => toast.error("Impossible de générer le PDF"))} data-testid="implantation-pdf-button"><Download />PDF à imprimer</Button>}>
        {!groups.length && <div className="text-sm text-muted-foreground">Aucun matériel sur cet événement.</div>}
        {!zones.length && groups.length > 0 && <div className="mb-3 text-sm text-muted-foreground">Ce lieu n'a pas encore d'espaces : ajoutez-les dans la fiche du lieu, puis affectez le matériel dans l'onglet Matériel.</div>}
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          {groups.map(({ z, lines }) => (
            <div key={z.id || "none"} className="rounded-2xl border border-border p-4" data-testid={`implantation-zone-${z.name}`}>
              <div className="flex items-center gap-2 font-semibold"><LayoutPanelTop className="h-[18px] w-[18px]" />{z.name}<span className="ml-auto text-[13px] font-normal text-[#737373]">{lines.reduce((n, l) => n + Number(l.qty), 0)} élément(s)</span></div>
              {z.notes && <div className="mt-1 text-[13px] text-muted-foreground">{z.notes}</div>}
              <div className="mt-2 divide-y divide-border text-sm">{lines.map((l) => <div key={l.equipment_id} className="flex gap-3 py-1.5"><b className="w-10 shrink-0">{l.qty} ×</b><span className="min-w-0 flex-1 truncate">{l.name}</span><span className="text-[13px] text-[#737373]">{l.ref}</span></div>)}</div>
            </div>
          ))}
        </div>
      </Section>
      <Section title="Documents signés" testid="event-documents">
        {!docs.length && <div className="text-sm text-muted-foreground">Les bons de livraison et devis signés apparaissent ici.</div>}
        <div className="divide-y divide-border">
          {docs.map((d) => <button key={d.ref} onClick={() => openFile(d.ref)} className="flex w-full items-center gap-3 py-3 text-left text-sm hover:underline" data-testid="event-document-row"><FileText className="h-[18px] w-[18px] shrink-0" /><b>{d.kind}</b><span className="truncate text-muted-foreground">{d.label}</span></button>)}
        </div>
      </Section>
    </div>
  );
}

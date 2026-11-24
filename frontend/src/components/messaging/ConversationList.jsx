import { useEffect, useState } from "react";
import { toast } from "sonner";
import { Paperclip, Star } from "lucide-react";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Loading, SearchPill } from "@/components/common";
import { api, errMsg } from "@/lib/api";
import { fmtDate } from "@/lib/constants";
import { LabelPicker } from "@/components/messaging/Labels";

const BOXES = [["inbox", "Réception"], ["unread", "Non lus"], ["starred", "Suivis"], ["sent", "Envoyés"], ["archived", "Archivés"], ["all", "Tous"], ["spam", "Spam"], ["trash", "Corbeille"]];
const BULK = [["read", "Lu"], ["unread", "Non lu"], ["archive", "Archiver"], ["star", "Suivre"], ["spam", "Spam"], ["trash", "Corbeille"]];
const pill = (on) => `h-7 rounded-full border px-3 text-xs font-medium transition-colors ${on ? "border-primary bg-primary text-white" : "border-border hover:bg-secondary"}`;

export const whenLabel = (iso) => {
  if (!iso) return "";
  const d = new Date(iso);
  return d.toDateString() === new Date().toDateString() ? d.toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" }) : fmtDate(iso, { day: "numeric", month: "short" });
};

export const CategoryBadge = ({ id, categories }) => (id
  ? <span className="inline-flex rounded-full bg-primary/10 px-2 py-0.5 text-[10.5px] font-semibold text-primary" data-testid="conversation-category">{categories[id] || id}</span>
  : null);

function Row({ r, active, onSelect, status, picked, toggle, write }) {
  const who = r.contact_name || r.counterpart?.name || r.counterpart?.email || "—";
  return (
    <div className={`flex border-b border-border transition-colors ${active ? "bg-secondary" : "hover:bg-secondary/50"}`}>
      {write && !r.deleted_at && <input type="checkbox" className="ml-3 mt-4 h-4 w-4 shrink-0" checked={picked} onChange={() => toggle(r.id)} aria-label="Sélectionner" data-testid={`conversation-pick-${r.id}`} />}
      <button type="button" onClick={() => onSelect(r.id)} data-testid={`conversation-row-${r.id}`} className="block min-w-0 flex-1 px-3 py-3 text-left">
        <div className="flex items-center gap-2">
          {r.unread && <span className="h-2 w-2 shrink-0 rounded-full bg-primary" data-testid="conversation-unread-dot" />}
          {r.is_starred && <Star className="h-3 w-3 shrink-0 fill-amber-400 text-amber-500" />}
          <span className={`min-w-0 flex-1 truncate text-sm ${r.unread ? "font-bold" : "font-medium"}`}>{who}</span>
          <span className="shrink-0 text-[11px] text-muted-foreground">{whenLabel(r.last_message_at)}</span>
        </div>
        <div className={`mt-0.5 truncate text-[13px] ${r.unread ? "font-semibold" : ""}`}>{r.subject}</div>
        <div className="mt-0.5 truncate text-xs text-muted-foreground">{r.last_direction === "out" ? "Vous : " : ""}{r.snippet}</div>
        <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
          <CategoryBadge id={r.category} categories={status.categories} />
          {!r.contact_id && <span className="rounded-full bg-amber-500/15 px-2 py-0.5 text-[10.5px] text-amber-700" data-testid={`conversation-unlinked-${r.id}`}>non rattachée</span>}
          {(r.label_ids || []).map((g) => { const l = status.labels.find((x) => x.gmail_id === g); return l ? <span key={g} className="max-w-[140px] truncate rounded-full bg-secondary px-2 py-0.5 text-[10.5px]">{l.name}</span> : null; })}
          {r.event_title && <span className="max-w-[160px] truncate rounded-full border border-border px-2 py-0.5 text-[10.5px]">{r.event_title}</span>}
          {r.has_attachments && <Paperclip className="h-3 w-3 text-muted-foreground" />}
          {r.purge_at && <span className="text-[10.5px] text-muted-foreground">Effacée le {fmtDate(r.purge_at)}</span>}
        </div>
      </button>
    </div>
  );
}

export const ConversationList = ({ rows, filters, setFilters, selected, onSelect, status, write, onChanged }) => {
  const [picked, setPicked] = useState([]);
  const [busy, setBusy] = useState(false);
  const set = (k, v) => setFilters({ ...filters, [k]: v });
  useEffect(() => { setPicked([]); }, [filters]);
  const toggle = (id) => setPicked((c) => (c.includes(id) ? c.filter((x) => x !== id) : [...c, id]));
  const bulk = (body, msg) => { setBusy(true); api.post("/messaging/conversations/bulk", { ids: picked, ...body }).then((r) => { toast.success(`${r.data.updated} conversation(s) : ${msg}`); setPicked([]); onChanged(); }).catch((e) => toast.error(errMsg(e))).finally(() => setBusy(false)); };
  const visible = (rows || []).filter((r) => !r.deleted_at).map((r) => r.id);
  return (
    <div className="card-soft flex h-full flex-col overflow-hidden" data-testid="conversation-list">
      <div className="space-y-2 border-b border-border p-3">
        <SearchPill value={filters.q} onChange={(v) => set("q", v)} placeholder="Rechercher… (from: label: has:attachment)" testid="messaging-search-input" className="" />
        <div className="flex flex-wrap gap-1.5">
          {BOXES.map(([k, l]) => (
            <button key={k} type="button" onClick={() => set("box", k)} data-testid={`messaging-box-${k}`} className={pill(filters.box === k)}>
              {l}{k === "inbox" && status.unread > 0 ? ` (${status.unread})` : ""}{k === "trash" && status.trash > 0 ? ` (${status.trash})` : ""}
            </button>
          ))}
        </div>
        <div className="flex flex-wrap gap-1.5" data-testid="messaging-gmail-categories">
          <button type="button" onClick={() => set("gcat", "")} className={pill(!filters.gcat)} data-testid="messaging-gcat-all">Toutes</button>
          {Object.entries(status.gmail_categories).map(([k, l]) => <button key={k} type="button" onClick={() => set("gcat", k)} className={pill(filters.gcat === k)} data-testid={`messaging-gcat-${k}`}>{l}</button>)}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Select value={filters.category || "all"} onValueChange={(v) => set("category", v === "all" ? "" : v)}>
            <SelectTrigger className="h-8 min-w-0 flex-1 text-xs" data-testid="messaging-category-filter"><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="all">Toutes les catégories</SelectItem>
              {Object.entries(status.categories).map(([k, l]) => <SelectItem key={k} value={k}>{l}</SelectItem>)}
            </SelectContent>
          </Select>
          <select className="h-8 min-w-0 flex-1 rounded-lg border border-border bg-background px-2 text-xs" value={filters.label_id} onChange={(e) => set("label_id", e.target.value)} data-testid="messaging-label-filter">
            <option value="">Tous les libellés</option>{status.labels.map((l) => <option key={l.id} value={l.gmail_id}>{l.name}</option>)}</select>
          <button type="button" onClick={() => set("unlinked", !filters.unlinked)} aria-pressed={filters.unlinked} data-testid="messaging-unlinked-filter" className={pill(filters.unlinked)}>Non rattachées</button>
        </div>
        {write && !!visible.length && filters.box !== "trash" && (
          <div className="flex flex-wrap items-center gap-1.5 text-xs" data-testid="messaging-bulk-bar">
            <label className="flex items-center gap-1"><input type="checkbox" checked={picked.length === visible.length} onChange={(e) => setPicked(e.target.checked ? visible : [])} data-testid="messaging-pick-all" />{picked.length ? `${picked.length} sélectionnée(s)` : "Tout sélectionner"}</label>
            {!!picked.length && <>{BULK.map(([k, l]) => <button key={k} type="button" disabled={busy} className={pill(false)} onClick={() => bulk({ action: k }, l.toLowerCase())} data-testid={`messaging-bulk-${k}`}>{l}</button>)}
              <LabelPicker labels={status.labels} disabled={busy} testid="messaging-bulk-label" onPick={(lid, archive) => bulk({ add_label_ids: [lid], archive }, archive ? "classées et archivées" : "classées")} /></>}
          </div>)}
      </div>
      <div className="scroll-thin min-h-0 flex-1 overflow-y-auto">
        {!rows ? <Loading /> : !rows.length
          ? <p className="p-8 text-center text-sm text-muted-foreground" data-testid="conversation-list-empty">Aucune conversation.</p>
          : rows.map((r) => <Row key={r.id} r={r} active={r.id === selected} onSelect={onSelect} status={status} picked={picked.includes(r.id)} toggle={toggle} write={write} />)}
      </div>
    </div>
  );
};

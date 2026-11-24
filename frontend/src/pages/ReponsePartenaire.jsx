import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import axios from "axios";
import { Loading } from "@/components/common";
import { fmtDate } from "@/lib/constants";

const BASE = `${process.env.REACT_APP_BACKEND_URL}/api/public/partner-requests`;
const inp = "h-12 w-full rounded-xl border border-border bg-background px-3 text-base";

export default function ReponsePartenaire() {
  const { token } = useParams();
  const [d, setD] = useState(null);
  const [items, setItems] = useState([]);
  const [f, setF] = useState({ conditions: "", comment: "" });
  const [err, setErr] = useState("");
  const [done, setDone] = useState(false);
  useEffect(() => { axios.get(`${BASE}/${token}`).then((r) => { setD(r.data); setItems(r.data.items.map((i) => ({ shortage_id: i.shortage_id, available_qty: i.qty, unit_cost: "" }))); }).catch(() => setErr("Ce lien est introuvable ou n'est plus valide.")); }, [token]);
  const up = (i, k, v) => setItems(items.map((x, j) => (j === i ? { ...x, [k]: v } : x)));
  const send = () => axios.post(`${BASE}/${token}/reply`, { items: items.map((x) => ({ ...x, available_qty: Number(x.available_qty) || 0, unit_cost: Number(x.unit_cost) || 0 })), ...f }).then(() => setDone(true)).catch((e) => setErr(e.response?.data?.detail || "Envoi impossible."));
  if (err && !d) return <div className="mx-auto max-w-lg px-4 py-10 text-center" data-testid="partner-reply-error">{err}</div>;
  if (!d) return <Loading />;
  const closed = !["envoyee", "repondue"].includes(d.status);
  return (
    <div className="mx-auto min-h-screen max-w-lg px-4 py-8" data-testid="partner-reply-page">
      <div className="mb-6 font-brand text-xl">{d.org}</div>
      <h1 className="text-2xl font-semibold">Demande de disponibilité de matériel</h1>
      <p className="mt-2 text-sm text-muted-foreground">Bonjour {d.partner_name}, pouvez-vous nous indiquer vos disponibilités et vos tarifs ? Du {fmtDate(d.date_from)} au {fmtDate(d.date_to)}{d.place ? ` · ${d.place}` : ""}{d.deadline ? ` · réponse souhaitée avant le ${fmtDate(d.deadline)}` : ""}.</p>
      {d.note && <p className="mt-2 rounded-xl bg-secondary p-3 text-sm">{d.note}</p>}
      {done ? <p className="mt-6 rounded-xl bg-emerald-500/10 p-4 text-emerald-700" data-testid="partner-reply-done">Merci, votre réponse est enregistrée.</p>
        : closed ? <p className="mt-6 rounded-xl bg-secondary p-4" data-testid="partner-reply-closed">Cette demande est close.</p> : (<>
          {d.items.map((it, i) => (<div key={it.shortage_id} className="mt-4 rounded-xl border border-border p-4" data-testid={`partner-item-${i}`}>
            <div className="font-semibold">{it.qty} × {it.name}</div>
            <div className="mt-2 grid grid-cols-2 gap-2"><label className="text-sm">Quantité disponible<input className={inp} type="number" min="0" value={items[i]?.available_qty ?? ""} onChange={(e) => up(i, "available_qty", e.target.value)} data-testid={`partner-qty-${i}`} /></label>
              <label className="text-sm">Prix unitaire HT (€)<input className={inp} type="number" min="0" step="0.01" value={items[i]?.unit_cost ?? ""} onChange={(e) => up(i, "unit_cost", e.target.value)} data-testid={`partner-price-${i}`} /></label></div>
          </div>))}
          <label className="mt-4 block text-sm">Conditions (enlèvement, caution, transport)<input className={inp} value={f.conditions} onChange={(e) => setF({ ...f, conditions: e.target.value })} data-testid="partner-conditions" /></label>
          <label className="mt-4 block text-sm">Commentaire<input className={inp} value={f.comment} onChange={(e) => setF({ ...f, comment: e.target.value })} /></label>
          {err && <p className="mt-3 text-sm text-red-600">{err}</p>}
          <button className="mt-6 h-12 w-full rounded-full bg-foreground text-base font-semibold text-background" onClick={send} data-testid="partner-reply-send">{d.answered ? "Mettre à jour ma réponse" : "Envoyer ma réponse"}</button></>)}
    </div>
  );
}

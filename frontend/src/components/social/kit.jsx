import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { api, errMsg } from "@/lib/api";

export const eur = (v) => (v === null || v === undefined ? "—" : Number(v).toLocaleString("fr-FR", { style: "currency", currency: "EUR", maximumFractionDigits: 0 }));
export const sel = "h-9 rounded-lg border border-border bg-card px-2 text-sm";
export const inp = "h-9 w-full rounded-lg border border-border bg-card px-2 text-sm";
export const today = () => new Date().toISOString().slice(0, 10);

export function useLoad(path) {
  const [d, setD] = useState(null);
  const load = useCallback(() => api.get(path).then((r) => setD(r.data)).catch((e) => { setD(false); toast.error(errMsg(e)); }), [path]);
  useEffect(() => { load(); }, [load]);
  return [d, load, setD];
}

export const run = (p, msg, then) => p.then((r) => { toast.success(msg || "Enregistré"); then?.(r.data); return r.data; }).catch((e) => toast.error(errMsg(e)));

export const dl = (path, name) => api.get(path, { responseType: "blob" }).then((r) => {
  const url = URL.createObjectURL(r.data);
  const a = document.createElement("a");
  a.href = url; a.download = name; a.click();
  setTimeout(() => URL.revokeObjectURL(url), 5000);
}).catch((e) => toast.error(errMsg(e)));

export const upload = (path, file, extra = {}) => {
  const fd = new FormData();
  Object.entries(extra).forEach(([k, v]) => fd.append(k, v));
  fd.append("file", file);
  return api.post(path, fd);
};

export const Note = ({ children, testid = "social-note" }) => <p className="mt-3 text-xs italic text-muted-foreground" data-testid={testid}>{children}</p>;
export const Kpi = ({ label, value, hint, testid }) => <div className="card-soft p-4" data-testid={testid}><div className="eyebrow">{label}</div><div className="mt-1 text-2xl font-bold">{value}</div>{hint && <div className="text-xs text-muted-foreground">{hint}</div>}</div>;
export const Alert = ({ a }) => <div className={`rounded-lg px-3 py-2 text-sm ${a.level === "high" ? "bg-red-500/10 text-red-700" : "bg-amber-500/10 text-amber-800"}`} data-testid={`social-alert-${a.kind || "x"}`}>{a.name ? <b>{a.name} : </b> : null}{a.label || a.text}{a.date ? ` (${a.date})` : ""}</div>;

export function T({ cols, rows, testid, empty = "Aucune donnée." }) {
  if (!rows?.length) return <p className="py-4 text-sm text-muted-foreground" data-testid={`${testid}-empty`}>{empty}</p>;
  return (
    <div className="overflow-x-auto rounded-xl border border-border" data-testid={testid}>
      <table className="w-full text-sm"><thead className="bg-secondary text-left text-xs text-muted-foreground"><tr>{cols.map((c) => <th key={c[0]} className="px-3 py-2 font-medium">{c[0]}</th>)}</tr></thead>
        <tbody>{rows.map((r, i) => <tr key={r.id || r.key || r.team_id || i} className="border-t border-border" data-testid={`${testid}-row-${i}`}>{cols.map((c) => <td key={c[0]} className="px-3 py-2 align-top">{typeof c[1] === "function" ? c[1](r, i) : r[c[1]] ?? "—"}</td>)}</tr>)}</tbody></table>
    </div>);
}

export function F({ label, children, className = "" }) {
  return <label className={`flex flex-col gap-1 text-xs text-muted-foreground ${className}`}>{label}{children}</label>;
}

export const In = ({ f, setF, k, type = "text", tid, ...p }) => <input className={inp} type={type} value={f[k] ?? ""} onChange={(e) => setF({ ...f, [k]: type === "number" ? (e.target.value === "" ? "" : Number(e.target.value)) : e.target.value })} data-testid={tid} {...p} />;
export const Pick = ({ f, setF, k, opts, tid, blank }) => <select className={inp} value={f[k] ?? ""} onChange={(e) => setF({ ...f, [k]: e.target.value })} data-testid={tid}>{blank !== undefined && <option value="">{blank}</option>}{opts.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select>;

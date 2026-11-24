import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { api, errMsg } from "@/lib/api";

const nf = (d) => new Intl.NumberFormat("fr-FR", { maximumFractionDigits: d });
export const show = (v, t) => (v == null ? "—" : t === "eur" ? `${nf(0).format(v)} €` : t === "pct" ? `${nf(1).format(v)} %` : typeof v === "number" ? nf(2).format(v) : v);

export const download = (url, params, name) => api.get(url, { params, responseType: "blob" }).then((r) => { const a = document.createElement("a"); a.href = URL.createObjectURL(r.data); a.download = name; a.click(); URL.revokeObjectURL(a.href); }).catch((e) => toast.error(errMsg(e)));

export function ReportView({ data, testid }) {
  return (
    <div className="space-y-5" data-testid={testid}>
      {data.kpis?.length > 0 && <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">{data.kpis.map((k) => (
        <div key={k.key} className="card-soft p-4"><div className="text-xs text-muted-foreground">{k.label}</div><div className="mt-1 text-2xl font-semibold" data-testid={`kpi-${k.key}`}>{show(k.value, k.t)}</div>{k.hint && <div className="text-xs text-muted-foreground">{k.hint}</div>}</div>))}</div>}
      {data.alerts?.length > 0 && <div className="rounded-xl bg-red-500/10 p-3 text-sm text-red-700" data-testid="report-alerts">{data.alerts.map((a) => <div key={a}>{a}</div>)}</div>}
      {data.tables.map((t) => (
        <div key={t.key} className="card-soft overflow-x-auto p-4" data-testid={`table-${t.key}`}><div className="eyebrow mb-2">{t.title}</div>
          {!t.rows.length ? <p className="text-sm text-muted-foreground">Aucune donnée sur la période.</p> : <table className="w-full text-sm"><thead><tr className="border-b border-border">{t.columns.map((c, i) => <th key={i} className={`whitespace-nowrap px-2 py-1.5 text-xs font-medium text-muted-foreground ${i ? "text-right" : "text-left"}`}>{c.l}</th>)}</tr></thead>
            <tbody>{t.rows.map((r, i) => <tr key={i} className={`border-b border-border last:border-0 ${t.bold?.includes(i) ? "font-semibold" : ""}`}>{r.map((v, j) => <td key={j} className={`whitespace-nowrap px-2 py-1.5 ${j ? "text-right" : ""}`}>{t.columns[j].t === "link" && v ? <Link className="underline" to={v.to}>{v.label}</Link> : show(v, t.columns[j].t)}</td>)}</tr>)}</tbody></table>}
        </div>))}
      {data.note && <p className="text-xs text-muted-foreground">{data.note}</p>}
    </div>);
}

const range = (p) => { const d = new Date(), y = d.getFullYear(), m = d.getMonth(), iso = (x) => `${x.getFullYear()}-${String(x.getMonth() + 1).padStart(2, "0")}-${String(x.getDate()).padStart(2, "0")}`;
  if (p === "mois") return [iso(new Date(y, m, 1)), iso(new Date(y, m + 1, 0))];
  if (p === "trimestre") return [iso(new Date(y, m - (m % 3), 1)), iso(new Date(y, m - (m % 3) + 3, 0))];
  if (p === "12m") return [iso(new Date(y - 1, m, d.getDate() + 1)), iso(d)];
  if (/^\d{4}$/.test(p)) return [`${p}-01-01`, `${p}-12-31`];
  return [`${y}-01-01`, `${y}-12-31`]; };

export function ReportTab({ tab, flt, NotConnected }) {
  const [data, setData] = useState(null);
  const [err, setErr] = useState("");
  const [start, end] = range(flt.period);
  const params = { start, end, activity: flt.activity || undefined };
  useEffect(() => { setData(null); setErr(""); api.get(`/finance/report/${tab}`, { params }).then((r) => setData(r.data)).catch((e) => setErr(errMsg(e))); }, [tab, start, end, flt.activity]); // eslint-disable-line react-hooks/exhaustive-deps
  if (err) return <p className="text-sm text-red-700" data-testid="report-error">{err}</p>;
  if (!data) return <p className="text-sm text-muted-foreground">Chargement…</p>;
  return (<div className="space-y-4">
    <div className="flex justify-end gap-2"><Button size="sm" variant="outline" onClick={() => download(`/finance/export/${tab}`, { ...params, format: "xlsx" }, `finance-${tab}.xlsx`)} data-testid="report-export-xlsx">Excel</Button><Button size="sm" variant="outline" onClick={() => download(`/finance/export/${tab}`, { ...params, format: "pdf" }, `finance-${tab}.pdf`)} data-testid="report-export-pdf">PDF</Button></div>
    {data.real && <NotConnected what={data.real} />}
    <ReportView data={data} testid={`report-${tab}`} />
  </div>);
}

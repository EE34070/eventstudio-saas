import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { Truck, Phone } from "lucide-react";

const d2 = (s) => (s ? `${s.slice(8, 10)}/${s.slice(5, 7)}/${s.slice(0, 4)}` : "");

export default function Suivi() {
  const { token } = useParams();
  const [d, setD] = useState(null);
  const [err, setErr] = useState(false);
  useEffect(() => {
    const load = () => fetch(`${process.env.REACT_APP_BACKEND_URL}/api/public/tracking/${token}`).then((r) => (r.ok ? r.json() : Promise.reject())).then(setD).catch(() => setErr(true));
    load();
    const t = setInterval(load, 60000);
    return () => clearInterval(t);
  }, [token]);
  if (err) return <main className="mx-auto max-w-lg p-8 text-center" data-testid="tracking-error">Ce lien de suivi n'est pas valide.</main>;
  if (!d) return <main className="p-8 text-center text-muted-foreground">Chargement…</main>;
  return (
    <main className="mx-auto max-w-lg p-6" data-testid="tracking-page">
      <div className="text-sm text-muted-foreground">{d.org}</div>
      <h1 className="mt-1 text-2xl font-bold">{d.type_label}</h1>
      <p className="text-sm text-muted-foreground">{d.event}{d.venue ? ` · ${d.venue}` : ""}</p>
      <div className="mt-6 rounded-2xl border border-border p-5">
        <div className="flex items-center gap-2 text-lg font-semibold" data-testid="tracking-status"><Truck className="h-5 w-5" />{d.status_label}</div>
        <p className="mt-2 text-sm">Créneau prévu : le {d2(d.date)}{d.window_start ? `, ${d.window_start}${d.window_end ? ` – ${d.window_end}` : ""}` : ""}</p>
        {d.status === "en_route" && <p className="mt-1 text-sm font-semibold" data-testid="tracking-eta">{d.eta ? `Arrivée estimée vers ${d.eta.slice(11)}` : `Parti à ${d.en_route_at.slice(11)} ; heure d'arrivée non estimée`}</p>}
        {d.signed_at && <p className="mt-1 text-sm">Bon signé le {d2(d.signed_at)} à {d.signed_at.slice(11)}</p>}
        <p className="mt-2 text-xs text-muted-foreground">Estimation indicative, sans position en direct. Page actualisée chaque minute.</p>
      </div>
      {d.vehicles.length > 0 && <div className="mt-4 rounded-2xl border border-border p-5 text-sm" data-testid="tracking-vehicles">{d.vehicles.map((v, i) => <div key={i}><b>{v.name}</b>{v.plate ? ` · ${v.plate}` : ""}</div>)}
        {d.drivers.map((c, i) => <div key={i} className="mt-1">Chauffeur : {c.first_name}{c.phone && <a className="ml-2 inline-flex items-center gap-1 underline" href={`tel:${c.phone}`}><Phone className="h-3.5 w-3.5" />{c.phone}</a>}</div>)}</div>}
      {d.items.length > 0 && <div className="mt-4 rounded-2xl border border-border p-5 text-sm" data-testid="tracking-items"><div className="mb-2 font-semibold">Matériel</div>{d.items.map((i, k) => <div key={k}>{i.qty} × {i.name}</div>)}</div>}
    </main>
  );
}

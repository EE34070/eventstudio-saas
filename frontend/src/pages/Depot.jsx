import { useEffect, useRef, useState } from "react";
import { useParams } from "react-router-dom";
import axios from "axios";
import { Loading } from "@/components/common";
import { chunked } from "@/components/communication/shared";

const http = axios.create({ baseURL: `${process.env.REACT_APP_BACKEND_URL}/api/public/media-drop` });

export default function Depot() {
  const { token } = useParams();
  const [d, setD] = useState(null);
  const [err, setErr] = useState("");
  const [handle, setHandle] = useState("");
  const [authorize, setAuthorize] = useState(true);
  const [rows, setRows] = useState([]);
  const [busy, setBusy] = useState(false);
  const input = useRef(null);
  useEffect(() => { http.get(`/${token}`).then((r) => { setD(r.data); setHandle(r.data.handle || ""); }).catch((e) => setErr(e.response?.status === 410 ? "Ce lien de dépôt est clôturé." : "Ce lien est introuvable ou n'est plus valide.")); }, [token]);
  const pick = async (e) => {
    const files = [...e.target.files];
    e.target.value = "";
    setBusy(true);
    for (const file of files) {
      const id = `${file.name}-${Date.now()}`;
      const set = (p) => setRows((c) => c.map((r) => (r.id === id ? { ...r, ...p } : r)));
      setRows((c) => [...c, { id, name: file.name, pct: 0, state: "envoi" }]);
      try { const r = await chunked(http, `/${token}/uploads`, file, { authorize, handle }, (pct) => set({ pct })); set({ pct: 100, state: r.duplicate ? "déjà reçu" : "reçu" }); } catch (x) { set({ state: x.response?.data?.detail || "échec" }); }
    }
    setBusy(false);
  };
  if (err) return <div className="mx-auto max-w-lg px-4 py-16 text-center" data-testid="depot-error">{err}</div>;
  if (!d) return <Loading />;
  return (
    <div className="mx-auto min-h-screen max-w-lg px-4 py-8" data-testid="depot-page">
      <div className="mb-6 flex items-center gap-2.5"><span className="brand-mark">{(d.org || "E")[0]}</span><span className="font-brand text-xl">{d.org}</span></div>
      <div className="card-soft p-6">
        <h1 className="font-display text-2xl" data-testid="depot-title">Bonjour {d.name}</h1>
        <p className="mt-1 text-sm text-muted-foreground" data-testid="depot-event">{d.event}</p>
        <p className="mt-4 whitespace-pre-wrap text-sm">{d.message}</p>
        <label className="mt-5 block text-sm font-medium">Votre identifiant Instagram (pour vous créditer)
          <div className="mt-1.5 flex items-center gap-1"><span>@</span><input className="h-12 w-full rounded-xl border border-border bg-background px-3 text-base" value={handle} onChange={(e) => setHandle(e.target.value)} data-testid="depot-handle" /></div></label>
        <label className="mt-4 flex items-start gap-2 text-sm"><input type="checkbox" className="mt-1" checked={authorize} onChange={(e) => setAuthorize(e.target.checked)} data-testid="depot-authorize" /><span>J'autorise {d.org} à publier ces fichiers sur ses réseaux sociaux et son site, avec mon crédit.</span></label>
        <input ref={input} type="file" hidden multiple accept="image/*,video/mp4,video/quicktime,video/webm,.heic,.heif" onChange={pick} data-testid="depot-input" />
        <button className="mt-5 h-12 w-full rounded-full bg-neutral-900 text-base font-semibold text-white disabled:opacity-60" disabled={busy} onClick={() => input.current.click()} data-testid="depot-pick">{busy ? "Envoi en cours…" : "Choisir des photos ou vidéos"}</button>
        <p className="mt-2 text-xs text-muted-foreground">Photos jusqu'à {d.max_photo_mb} Mo, vidéos jusqu'à {d.max_video_mb} Mo. Vous pouvez revenir sur cette page pour en ajouter. Déjà reçus : {d.received}.</p>
        <div className="mt-4 space-y-2" data-testid="depot-files">{rows.map((r) => (
          <div key={r.id} className="text-sm" data-testid="depot-file"><div className="flex justify-between"><span className="truncate">{r.name}</span><span data-testid="depot-file-state">{r.state === "envoi" ? `${r.pct} %` : r.state}</span></div>
            <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-secondary"><div className="h-full bg-neutral-900" style={{ width: `${r.pct}%` }} /></div></div>))}</div>
      </div>
    </div>);
}

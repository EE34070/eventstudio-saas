import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, errMsg } from "@/lib/api";
import "./wp.css";

/* Module Wedding planner : client API, thème (design validé par l'organisatrice), petits composants. */

/** « Voir comme les mariés » : tant qu'un aperçu est ouvert, les appels de l'espace des mariés portent l'identifiant du mariage (lecture seule côté serveur). */
let previewId = null;
export const setPreview = (id) => { previewId = id || null; };
const pv = (p) => (previewId && p.startsWith("/portal/wedding") ? { headers: { "x-view-as-wedding": previewId } } : {});

export const get = (p) => api.get(p, pv(p)).then((r) => r.data);
export const send = (method, p, body) => api.request({ method, url: p, data: body, ...pv(p) }).then((r) => r.data);

export function useWq(key, path, opts = {}) {
  return useQuery({ queryKey: ["wp", previewId, ...key], queryFn: () => get(path), staleTime: 0, ...opts });
}

/** Mutation qui rafraîchit tout le module : une seule saisie, visible partout. */
export function useWm(fn, onDone) {
  const qc = useQueryClient();
  return useMutation({ mutationFn: fn, onSuccess: (r) => { qc.invalidateQueries({ queryKey: ["wp"] }); onDone?.(r); }, onError: (e) => toast(errMsg(e)) });
}

export const fmtDate = (d, lang = "fr") => (d ? new Date(`${d}T12:00:00`).toLocaleDateString(lang === "en" ? "en-GB" : "fr-FR", { day: "numeric", month: "long", year: "numeric" }) : "");
export const money = (n) => (n == null ? "" : `${Number(n).toLocaleString("fr-FR")} $`);
export const num = (v) => (String(v).trim() === "" ? null : Number(String(v).replace(/\s/g, "").replace(",", ".")));

const fontsLoaded = new Set();
function loadFonts(d) {
  const fam = [d.font_display, d.font_body].filter(Boolean);
  const key = fam.join("|");
  if (!fam.length || fontsLoaded.has(key)) return;
  fontsLoaded.add(key);
  const l = document.createElement("link");
  l.rel = "stylesheet";
  l.href = `https://fonts.googleapis.com/css2?${fam.map((f) => `family=${encodeURIComponent(f)}:ital,wght@0,300;0,400;0,500;1,400;1,500`).join("&")}&display=swap`;
  document.head.appendChild(l);
}

export function designVars(d = {}) {
  loadFonts(d);
  const v = {};
  const map = { primary_color: "--b-primary", background: "--b-bg", surface: "--b-surface", ink: "--b-ink", muted: "--b-muted", line: "--b-line", soft: "--b-soft", alert: "--b-alert" };
  Object.entries(map).forEach(([k, css]) => { if (d[k]) v[css] = d[k]; });
  if (d.font_display) v["--b-display"] = `'${d.font_display}', Georgia, serif`;
  if (d.font_body) v["--b-body"] = `'${d.font_body}', system-ui, sans-serif`;
  return v;
}

/* Confirmations : petit message en bas de page, jamais de boîte d'alerte du navigateur. */
let push = null;
export const toast = (m) => push?.(m);
export function Toaster() {
  const [msg, setMsg] = useState(null);
  useEffect(() => {
    let t;
    push = (m) => { setMsg(m); clearTimeout(t); t = setTimeout(() => setMsg(null), 2600); };
    return () => { push = null; clearTimeout(t); };
  }, []);
  return msg ? <div className="wp-toast" role="status">{msg}</div> : null;
}

/** Racine des pages de l'organisatrice : fond et thème du module. */
export function Wp({ children }) {
  const { data: d } = useWq(["design"], "/wedding/design", { staleTime: 600000 });
  return (
    <div className="wp wp-page" style={designVars(d)}>
      {children}
      <Toaster />
    </div>
  );
}

export function Modal({ onClose, children }) {
  useEffect(() => {
    const k = (e) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", k);
    return () => window.removeEventListener("keydown", k);
  }, [onClose]);
  return <div className="wp-modal" onClick={(e) => e.target === e.currentTarget && onClose()}><div role="dialog" aria-modal="true">{children}</div></div>;
}

export function Field({ label, value, onChange, type = "text", disabled, placeholder }) {
  return (
    <div>
      <label className="l">{label}
        <input type={type} value={value ?? ""} disabled={disabled} placeholder={placeholder} onChange={(e) => onChange(e.target.value)} style={{ marginTop: 4, textTransform: "none", letterSpacing: 0 }} />
      </label>
    </div>
  );
}

export const Section = ({ title, kicker, children }) => <div className="sec">{kicker && <div className="kicker">{kicker}</div>}{title && <h3>{title}</h3>}{children}</div>;
export const Loading = () => <p className="muted">Chargement…</p>;

export async function download(path, filename) {
  const r = await api.get(path, { responseType: "blob" });
  const url = URL.createObjectURL(r.data);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 4000);
}

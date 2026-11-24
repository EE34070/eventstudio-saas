import { useState } from "react";
import { toast } from "sonner";
import { Languages } from "lucide-react";
import { api, errMsg } from "@/lib/api";

export const LANGS = [["fr-FR", "🇫🇷", "Français"], ["en-US", "🇺🇸", "English (US)"], ["en-GB", "🇬🇧", "English (UK)"], ["es-ES", "🇪🇸", "Español"], ["it-IT", "🇮🇹", "Italiano"], ["de-DE", "🇩🇪", "Deutsch"]];
export const langLabel = (code) => { const l = LANGS.find((x) => x[0] === code); return l ? `${l[1]} ${l[2]}` : "🇫🇷 Français"; };
export const isFr = (code) => (code || "fr").startsWith("fr");

export const LanguageSelect = ({ value, onChange, testid, auto, disabled, className = "" }) => (
  <select disabled={disabled} className={`h-10 w-full rounded-lg border border-border bg-background px-3 text-sm ${className}`} value={value || (auto ? "" : "fr-FR")} onChange={(e) => onChange(e.target.value)} data-testid={testid}>
    {auto && <option value="">{auto}</option>}
    {LANGS.map(([code, flag, label]) => <option key={code} value={code}>{flag} {label}</option>)}
  </select>
);

export function TranslateButton({ texts, onDone, context = "", testid, label = "Traduire (IA)" }) {
  const [busy, setBusy] = useState(false);
  const run = async () => {
    setBusy(true);
    try { const r = await api.post("/translate", { texts, target: "en", context }); onDone(r.data); toast.success("Traduction générée : relisez-la avant d'enregistrer"); } catch (e) { toast.error(errMsg(e)); }
    setBusy(false);
  };
  return <button type="button" disabled={busy} onClick={run} data-testid={testid} className="inline-flex h-8 items-center gap-1.5 rounded-full border border-border px-3 text-xs font-semibold hover:bg-secondary disabled:opacity-50"><Languages className="h-3.5 w-3.5" />{busy ? "Traduction…" : label}</button>;
}

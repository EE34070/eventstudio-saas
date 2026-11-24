import { lazy } from "react";
import { useSearchParams } from "react-router-dom";
import { useMe } from "@/context/MeContext";
import Team from "@/pages/Team";

const Prestataires = lazy(() => import("@/pages/Prestataires"));
const StaffAdmin = lazy(() => import("@/pages/StaffAdmin"));

export default function Equipe() {
  const { can } = useMe();
  const [sp, setSp] = useSearchParams();
  const tabs = [["salaries", "Salariés"], ...(can("providers:manage") ? [["prestataires", "Prestataires"], ["staff", "Staff"]] : [])];
  const vue = tabs.some(([k]) => k === sp.get("vue")) ? sp.get("vue") : "salaries";
  return (
    <div data-testid="equipe-page">
      <div className="mb-6 inline-flex rounded-full border border-border bg-card p-1" role="tablist">
        {tabs.map(([k, l]) => <button key={k} role="tab" aria-selected={vue === k} onClick={() => setSp(k === "salaries" ? {} : { vue: k })} data-testid={`equipe-tab-${k}`} className={`rounded-full px-5 py-2 text-sm font-semibold transition-colors ${vue === k ? "bg-foreground text-background" : "text-muted-foreground hover:text-foreground"}`}>{l}</button>)}
      </div>
      {vue === "salaries" ? <Team /> : vue === "prestataires" ? <Prestataires /> : <StaffAdmin />}
    </div>
  );
}

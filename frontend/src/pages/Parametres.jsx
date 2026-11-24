import { useCallback, useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { toast } from "sonner";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { PageHeader } from "@/components/common";
import { api, errMsg } from "@/lib/api";
import { useMe } from "@/context/MeContext";
import { Members } from "@/components/admin/Members";
import { AccessProfiles, OverridesDialog, ManageDialog } from "@/components/admin/AccessProfiles";
import { PortalUsers, PortalModules, Templates, Settings, Journal } from "@/pages/Acces";
import { OrgForm, OrgModules, ModuleDefaults } from "@/pages/Entreprise";
import { MenuVisibility } from "@/components/layout/MenuVisibility";
import { StockSettings } from "@/components/stock/Availability";
import { PricingSettings } from "@/components/settings/PricingSettings";
import { DocumentTemplates } from "@/components/billing/QuoteDocs";
import { TrashBin } from "@/components/Trash";

function MembersTab() {
  const [d, setD] = useState(null);
  const [adj, setAdj] = useState(null);
  const [man, setMan] = useState(null);
  const [tick, setTick] = useState(0);
  const load = useCallback(() => api.get("/access-profiles").then((r) => { setD(r.data); setTick((x) => x + 1); }).catch((e) => toast.error(errMsg(e))), []);
  useEffect(() => { load(); }, [load]);
  return (
    <div data-testid="members-tab">
      <Members onAdjust={setAdj} onManage={setMan} refreshKey={tick} />
      {adj && <OverridesDialog u={adj} all={d?.all_perms || []} onClose={() => setAdj(null)} onSaved={load} />}
      {man && <ManageDialog u={man} users={d?.users || []} onClose={() => setMan(null)} onSaved={load} />}
    </div>);
}

const U = "users:manage", O = "org:write";
const TABS = [
  ["membres", "Membres", U, () => <MembersTab />],
  ["profils", "Profils d'accès", U, () => <AccessProfiles />],
  ["modules", "Modules", O, (can) => <><OrgModules write /><ModuleDefaults write />{can(U) && <div className="mt-8"><h3 className="mb-3 font-semibold">Modules des espaces clients et prestataires</h3><PortalModules /></div>}</>],
  ["organisation", "Organisation / Société", O, () => <OrgForm write />],
  ["emails", "E-mails", U, () => <Templates />],
  ["reglages", "Réglages & RGPD", U, () => <Settings />],
  ["journal", "Journal", U, () => <Journal />],
  ["menu", "Menu par rôle", O, () => <MenuVisibility />],
  ["portails", "Comptes des portails", U, () => <PortalUsers />],
  ["stock", "Stock & options", O, () => <StockSettings />],
  ["tarification", "Tarification", O, () => <PricingSettings write />],
  ["documents", "Modèles de documents", O, () => <DocumentTemplates write />],
  ["corbeille", "Corbeille", O, () => <TrashBin />],
];

export default function Parametres() {
  const { can } = useMe();
  const [sp, setSp] = useSearchParams();
  const tabs = TABS.filter((t) => can(t[2]));
  const tab = (tabs.find((t) => t[0] === sp.get("tab")) || tabs[0])[0];
  return (
    <div data-testid="parametres-page">
      <PageHeader eyebrow="Administration" title="Paramètres" subtitle="Membres, profils d'accès, modules, société, e-mails et journal." />
      <Tabs value={tab} onValueChange={(k) => setSp({ tab: k })}>
        <TabsList className="mb-5 h-auto flex-wrap justify-start">{tabs.map(([k, l]) => <TabsTrigger key={k} value={k} data-testid={`parametres-tab-${k}`}>{l}</TabsTrigger>)}</TabsList>
        {tabs.map(([k, , , render]) => <TabsContent key={k} value={k}>{tab === k && render(can)}</TabsContent>)}
      </Tabs>
    </div>
  );
}

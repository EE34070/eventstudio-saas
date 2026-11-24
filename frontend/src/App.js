import { lazy, Suspense, useEffect, useState } from "react";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { Show, UserProfile, useUser } from "@clerk/react";
import ClerkAuthProvider from "@/components/auth/ClerkAuthProvider";
import { Toaster } from "@/components/ui/sonner";
import { MeProvider, useMe } from "@/context/MeContext";
import AppShell from "@/components/layout/AppShell";
import { Loading } from "@/components/common";
import { SignInPage, SignUpPage } from "@/pages/AuthPages";

const Onboarding = lazy(() => import("@/pages/Onboarding"));
const Dashboard = lazy(() => import("@/pages/Dashboard"));
const Events = lazy(() => import("@/pages/Events"));
const EventDetail = lazy(() => import("@/pages/EventDetail"));
const Planning = lazy(() => import("@/pages/Planning"));
const Catalogue = lazy(() => import("@/pages/Catalogue"));
const Chargement = lazy(() => import("@/pages/Chargement"));
const Billing = lazy(() => import("@/pages/Billing"));
const Contacts = lazy(() => import("@/pages/Contacts"));
const Venues = lazy(() => import("@/pages/Venues"));
const Team = lazy(() => import("@/pages/Equipe"));
const Todo = lazy(() => import("@/pages/Todo"));
const Entrepots = lazy(() => import("@/pages/Entrepots"));
const Logistique = lazy(() => import("@/pages/Logistique"));
const adm = (n) => lazy(() => import("@/pages/Admin").then((m) => ({ default: m[n] })));
const Expenses = adm("Expenses");
const Purchases = adm("Purchases");
const Subscriptions = lazy(() => import("@/pages/Contracts"));
const Finance = lazy(() => import("@/pages/Finance"));
const Communication = lazy(() => import("@/pages/Communication"));
const Depot = lazy(() => import("@/pages/Depot"));
const Vehicles = adm("Vehicles");
const Parametres = lazy(() => import("@/pages/Parametres"));
const OLD_TABS = { access: "membres", acces: "membres", modules: "modules", org: "organisation", menu: "menu", stock: "stock", trash: "corbeille", pricing: "tarification", docs: "documents" };
const OldSettings = () => { const t = new URLSearchParams(window.location.search).get("tab"); return <Navigate to={`/parametres?tab=${OLD_TABS[t] || t || "modules"}`} replace />; };
const ComingSoon = lazy(() => import("@/pages/ComingSoon"));
const PublicQuote = lazy(() => import("@/pages/PublicQuote"));
const Suivi = lazy(() => import("@/pages/Suivi"));
const Livraison = lazy(() => import("@/pages/Livraison"));
const Messagerie = lazy(() => import("@/pages/Messagerie"));
const Prestataires = lazy(() => import("@/pages/Prestataires"));
const DemandePrestataire = lazy(() => import("@/pages/DemandePrestataire"));
const ReponsePrestataire = lazy(() => import("@/pages/ReponsePrestataire"));
const DispoDj = lazy(() => import("@/pages/DispoDj"));
const DemandeNouvelle = lazy(() => import("@/pages/DemandeNouvelle"));
const Demandes = lazy(() => import("@/pages/DemandeNouvelle").then((m) => ({ default: m.Demandes })));
const Crm = lazy(() => import("@/pages/Crm"));
const Musique = lazy(() => import("@/pages/Musique"));
const GuestMusic = lazy(() => import("@/portal/Music").then((m) => ({ default: m.GuestMusic })));
const StaffAdmin = lazy(() => import("@/pages/StaffAdmin"));
const DjAdmin = lazy(() => import("@/pages/DjAdmin"));
const JoinPage = lazy(() => import("@/portal/Staff").then((m) => ({ default: m.JoinPage })));
const Portal = lazy(() => import("@/portal/Portal"));
const PortalPreview = lazy(() => import("@/portal/Portal").then((m) => ({ default: m.PortalPreview })));
const LegalPage = lazy(() => import("@/portal/Portal").then((m) => ({ default: m.LegalPage })));
const ImportCatalogue = lazy(() => import("@/pages/ImportCatalogue"));
const AAcheter = lazy(() => import("@/pages/AAcheter"));
const ReponsePartenaire = lazy(() => import("@/pages/ReponsePartenaire"));
const Social = lazy(() => import("@/pages/Social"));
const MonEspace = lazy(() => import("@/pages/MonEspace"));
const Relances = lazy(() => import("@/pages/Relances"));

const SOON = ["compta", "commercial", "documents", "ecrans"];

function ChoosePassword({ user, onDone }) {
  const [pw, setPw] = useState("");
  const [err, setErr] = useState("");
  const save = (e) => { e.preventDefault(); setErr(""); user.updatePassword({ newPassword: pw, signOutOfOtherSessions: false }).then(onDone).catch((x) => setErr(x.errors?.[0]?.longMessage || x.errors?.[0]?.message || "Mot de passe refusé : choisissez-en un plus long ou moins courant.")); };
  return (
    <form onSubmit={save} className="mx-auto mt-24 max-w-sm p-6" data-testid="choose-password">
      <h1 className="text-2xl font-bold">Bienvenue ! Choisissez votre mot de passe</h1>
      <p className="mb-4 mt-2 text-sm text-muted-foreground">Il vous servira pour vos prochaines connexions avec {user.primaryEmailAddress?.emailAddress}. Vous pouvez aussi passer cette étape et vous connecter avec un code reçu par e-mail.</p>
      <input type="password" autoComplete="new-password" minLength={8} required value={pw} onChange={(e) => setPw(e.target.value)} placeholder="Mot de passe (8 caractères minimum)" className="h-11 w-full rounded-lg border border-border bg-background px-3 text-sm" data-testid="choose-password-input" />
      {err && <p className="mt-2 text-sm text-red-600" data-testid="choose-password-error">{err}</p>}
      <div className="mt-4 flex items-center gap-4"><button type="submit" className="h-11 rounded-full bg-foreground px-6 text-sm font-semibold text-background" data-testid="choose-password-submit">Enregistrer</button><button type="button" className="text-sm underline" onClick={onDone} data-testid="choose-password-skip">Plus tard</button></div>
    </form>
  );
}

function Gate() {
  const { me, error, can } = useMe();
  const { user } = useUser();
  const [pwDone, setPwDone] = useState(false);
  useEffect(() => { if (user && localStorage.getItem(`pw-skip-${user.id}`)) setPwDone(true); }, [user]);
  if (error) return <p className="p-8 text-sm">Impossible de charger votre compte. Rechargez la page.</p>;
  if (!me) return <Loading />;
  if (["client", "provider"].includes(me.user.role)) return <Portal />;
  if (!me.org) return <Onboarding />;
  if (!pwDone && user && !user.passwordEnabled && !user.externalAccounts?.length) return <ChoosePassword user={user} onDone={() => { localStorage.setItem(`pw-skip-${user.id}`, "1"); setPwDone(true); }} />;
  if (me.needs_2fa) return <div className="mx-auto max-w-3xl p-6" data-testid="2fa-required"><h1 className="text-2xl font-bold">Double authentification obligatoire</h1><p className="mb-4 mt-2 text-sm text-muted-foreground">Activez la validation en deux étapes dans l'onglet Sécurité ci-dessous, puis rechargez la page.</p><UserProfile routing="hash" /></div>;
  return (
    <Routes>
      {can("users:manage") && <Route path="apercu/:uid" element={<PortalPreview />} />}
      <Route element={<AppShell />}>
        <Route index element={<Navigate to="/dashboard" replace />} />
        <Route path="dashboard" element={<Dashboard />} />
        <Route path="evenements" element={<Events />} />
        <Route path="evenements/:id" element={<EventDetail />} />
        <Route path="planning" element={<Planning />} />
        <Route path="catalogue" element={<Catalogue />} />
        {me?.user?.role === "admin" && <Route path="import-catalogue" element={<ImportCatalogue />} />}
        <Route path="chargement" element={<Chargement />} />
        <Route path="livraison" element={<Livraison />} />
        {can("finance:read") && <Route path="relances" element={<Relances />} />}
        {can("finance:read") && <Route path="devis-factures" element={<Billing />} />}
        {can("messages:read") && <Route path="messagerie" element={<Messagerie />} />}
        {can("providers:manage") && <Route path="prestataires" element={<Prestataires />} />}
        {can("providers:manage") && <Route path="prestataires/demandes/:id" element={<DemandePrestataire />} />}
        {can("events:write") && <Route path="demande/nouvelle" element={<DemandeNouvelle />} />}
        <Route path="demandes" element={<Demandes />} />
        {can("crm:manage") && <Route path="crm" element={<Crm />} />}
        <Route path="contacts" element={<Contacts />} />
        <Route path="lieux" element={<Venues />} />
        <Route path="equipe" element={<Team />} />
        <Route path="todo" element={<Todo />} />
        <Route path="entrepots" element={<Entrepots />} />
        <Route path="logistique" element={<Logistique />} />
        <Route path="vehicules" element={<Vehicles />} />
        <Route path="notes-de-frais" element={<Expenses />} />
        {can("finance:read") && <Route path="factures-achat" element={<Purchases />} />}
        {can("finance:read") && <Route path="a-acheter" element={<AAcheter />} />}
        {can("finance:read") && <Route path="abonnements" element={<Subscriptions />} />}
        {can("pilot:view") && <Route path="finance" element={<Finance />} />}
        {can("social:view") && <Route path="social" element={<Social />} />}
        <Route path="mon-espace" element={<MonEspace />} />
        {can("comms:view") && <Route path="communication" element={<Communication />} />}
        <Route path="musique-plans" element={<Musique />} />
        {can("providers:manage") && <Route path="staff" element={<StaffAdmin />} />}
        {can("providers:manage") && <Route path="dj" element={<DjAdmin />} />}
        {(can("users:manage") || can("org:write")) && <Route path="parametres" element={<Parametres />} />}
        <Route path="entreprise" element={<OldSettings />} />
        <Route path="acces" element={<Navigate to="/parametres?tab=membres" replace />} />
        {SOON.map((s) => <Route key={s} path={s} element={<ComingSoon slug={s} />} />)}
        <Route path="*" element={<Navigate to="/dashboard" replace />} />
      </Route>
    </Routes>
  );
}

function Protected() {
  return (
    <>
      <Show when="signed-in"><MeProvider><Gate /></MeProvider></Show>
      <Show when="signed-out"><Navigate to="/sign-in" replace /></Show>
    </>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <ClerkAuthProvider>
        <Suspense fallback={<Loading />}>
        <Routes>
          <Route path="/sign-in/*" element={<SignInPage />} />
          <Route path="/sign-up/*" element={<SignUpPage />} />
          <Route path="/devis/v/:token" element={<PublicQuote view />} />
          <Route path="/devis/:token" element={<PublicQuote />} />
          <Route path="/suivi/:token" element={<Suivi />} />
          <Route path="/reponse/:token" element={<ReponsePrestataire />} />
          <Route path="/dispo-dj/:token" element={<DispoDj />} />
          <Route path="/depot/:token" element={<Depot />} />
          <Route path="/partenaire/:token" element={<ReponsePartenaire />} />
          <Route path="/legal/:org/:page" element={<LegalPage />} />
          <Route path="/musique/:token" element={<GuestMusic />} />
          <Route path="/rejoindre" element={<JoinPage />} />
          <Route path="/*" element={<Protected />} />
        </Routes>
        </Suspense>
        <Toaster position="top-right" richColors />
      </ClerkAuthProvider>
    </BrowserRouter>
  );
}

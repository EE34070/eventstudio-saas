import { useEffect, useState } from "react";
import axios from "axios";
import { SignIn, SignUp, useClerk } from "@clerk/react";
import { frFR, enUS } from "@clerk/localizations";

const HERO = "https://images.unsplash.com/photo-1574482211311-45a2169db57c?crop=entropy&cs=srgb&fm=jpg&q=80&w=1400";

const Layout = ({ children }) => (
  <div className="flex min-h-screen bg-background">
    <div className="relative hidden w-1/2 overflow-hidden lg:flex">
      <img src={HERO} alt="Réception en plein air" className="absolute inset-0 h-full w-full object-cover" />
      <div className="absolute inset-0 bg-gradient-to-t from-black/70 via-black/20 to-transparent" />
      <div className="relative mt-auto p-12 text-white">
        <div className="eyebrow !text-white/70 mb-3">Exclusivity Events · ERP</div>
        <h1 className="font-display text-5xl leading-tight">De la demande<br />à la clôture.</h1>
        <p className="mt-4 max-w-md text-white/80">Devis, matériel, équipes et lieux réunis pour orchestrer chaque mariage et soirée d'entreprise.</p>
      </div>
    </div>
    <div className="flex flex-1 items-center justify-center p-6" data-testid="auth-container">{children}</div>
  </div>
);

const btn = "mt-4 h-11 rounded-full bg-foreground px-6 text-sm font-semibold text-background disabled:opacity-50";

function TicketSignIn({ ticket }) {
  const clerk = useClerk();
  const [state, setState] = useState("loading");
  const [msg, setMsg] = useState("");
  useEffect(() => {
    if (!clerk.loaded) return undefined;
    let off = false;
    (async () => {
      try {
        if (clerk.session) await clerk.signOut({ redirectUrl: window.location.href });
        const r = await clerk.client.signIn.create({ strategy: "ticket", ticket });
        if (r.status !== "complete") throw new Error("incomplete");
        await clerk.setActive({ session: r.createdSessionId });
        window.location.replace("/");
      } catch (e) { console.error("ticket sign-in", e?.errors?.[0]?.code || e?.message); if (!off) setState("error"); }
    })();
    return () => { off = true; };
  }, [clerk.loaded]); // eslint-disable-line react-hooks/exhaustive-deps
  const renew = () => { setState("sending"); axios.post(`${process.env.REACT_APP_BACKEND_URL}/api/public/invitations/renew`, { ticket }).then(() => setState("sent")).catch((e) => { setMsg(typeof e.response?.data?.detail === "string" ? e.response.data.detail : "Ce lien n'est plus reconnu. Demandez une nouvelle invitation à votre responsable."); setState("error"); }); };
  return (
    <Layout><div className="max-w-sm" data-testid="ticket-signin">
      {state === "loading" && <p className="text-sm text-muted-foreground">Connexion en cours…</p>}
      {state === "sent" && <p className="text-sm" data-testid="ticket-renew-sent">Un nouveau lien vient d'être envoyé à votre adresse e-mail. Ouvrez-le depuis cet appareil.</p>}
      {["error", "sending"].includes(state) && <>
        <h1 className="text-2xl font-bold">Ce lien n'est plus valable</h1>
        <p className="mt-2 text-sm text-muted-foreground" data-testid="ticket-error">Il a expiré, a déjà été utilisé, ou a été remplacé par un lien plus récent. Utilisez le dernier e-mail reçu, ou demandez un nouveau lien.</p>
        {msg && <p className="mt-2 text-sm text-red-600" data-testid="ticket-renew-error">{msg}</p>}
        <button className={btn} disabled={state === "sending"} onClick={renew} data-testid="ticket-renew">Recevoir un nouveau lien</button>
        <a href="/sign-in" className="ml-4 text-sm underline">J'ai déjà un accès</a>
      </>}
    </div></Layout>
  );
}

export function SignInPage() {
  const ticket = new URLSearchParams(window.location.search).get("__clerk_ticket");
  return ticket ? <TicketSignIn ticket={ticket} /> : <PlainSignIn />;
}

function PlainSignIn() {
  const clerk = useClerk();
  const [fr, setFr] = useState(navigator.language.startsWith("fr"));
  const flip = () => { clerk.__internal_updateProps?.({ options: { localization: fr ? enUS : frFR } }); setFr(!fr); };
  return (
    <Layout><div><div className="mb-3 flex items-center justify-between text-sm"><span className="text-muted-foreground">{fr ? "Saisissez votre e-mail pour recevoir votre lien ou votre code de connexion." : "Enter your e-mail to receive your sign-in link or code."}</span>
      <button className="ml-3 font-semibold underline" onClick={flip} data-testid="signin-lang">{fr ? "EN" : "FR"}</button></div><SignIn routing="path" path="/sign-in" signUpUrl="/sign-up" withSignUp /></div></Layout>
  );
}

export const SignUpPage = () => (
  <Layout><SignUp routing="path" path="/sign-up" signInUrl="/sign-in" /></Layout>
);

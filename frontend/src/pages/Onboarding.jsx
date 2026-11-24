import { useState } from "react";
import { UserButton } from "@clerk/react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Field } from "@/components/common";
import { api, errMsg } from "@/lib/api";
import { useMe } from "@/context/MeContext";

export default function Onboarding() {
  const { reload } = useMe();
  const [name, setName] = useState("");
  const [city, setCity] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true);
    try {
      await api.post("/onboarding", { company_name: name, city });
      await reload();
    } catch (err) {
      toast.error(errMsg(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-background p-6">
      <div className="absolute right-6 top-6"><UserButton /></div>
      <form onSubmit={submit} className="card-soft w-full max-w-md p-8 fade-up" data-testid="onboarding-form">
        <div className="eyebrow mb-2">Bienvenue</div>
        <h1 className="font-display text-3xl">Créez votre entreprise</h1>
        <p className="mt-2 text-sm text-muted-foreground">
          Votre compte n'est rattaché à aucune entreprise. Créez la vôtre (vous en serez l'administrateur) ou demandez à votre responsable de vous ajouter à son équipe avec votre e-mail.
        </p>
        <div className="mt-6 space-y-4">
          <Field label="Nom de l'entreprise"><Input data-testid="onboarding-company-input" value={name} onChange={(e) => setName(e.target.value)} required minLength={2} /></Field>
          <Field label="Ville"><Input data-testid="onboarding-city-input" value={city} onChange={(e) => setCity(e.target.value)} /></Field>
        </div>
        <Button data-testid="onboarding-submit-button" className="mt-6 w-full" disabled={busy}>Créer mon espace</Button>
      </form>
    </div>
  );
}

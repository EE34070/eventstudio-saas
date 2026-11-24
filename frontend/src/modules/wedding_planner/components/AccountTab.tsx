import { useQuery } from "@tanstack/react-query";
import { useWpMutation, wp, type Rights, type Wedding } from "../api";
import { Loading, Section, toast } from "../ui";

const RIGHTS: [keyof Rights, string][] = [["budget", "Budget global visible par les mariés"], ["vendor_prices", "Tarifs des prestataires visibles"],
  ["dday_planning", "Planning du jour J visible"], ["documents", "Documents partagés visibles"], ["edit_info", "Les mariés peuvent modifier la fiche informations"]];
const SECTIONS: [string, string][] = [["food", "Repas et boissons"], ["vendors", "Nos prestataires"], ["guests", "Guest list"], ["seating", "Plan de table"],
  ["budget", "Budget et paiements"], ["group_photos", "Photos de groupe"], ["music", "Musiques"], ["design", "Design et ambiance"],
  ["planning", "Planning"], ["documents", "Récapitulatif et documents"]];
const STATUS: Record<string, [string, string]> = { accepted: ["ok", "Invité, connecté"], pending: ["warn", "Invitation envoyée"],
  not_invited: ["", "Pas encore invité"], revoked: ["warn", "Invitation annulée"] };

export function AccountTab({ w }: { w: Wedding }) {
  const { data, isLoading } = useQuery({ queryKey: ["wp", "account", w.id], queryFn: () => wp.account(w.id) });
  const invite = useWpMutation((i: number) => wp.invite(w.id, i), () => toast("Invitation envoyée"));
  const rights = useWpMutation((r: Rights) => wp.rights(w.id, r), () => toast("Droit mis à jour"));
  const lang = useWpMutation((l: string) => wp.lang(w.id, l), () => toast("Langue de l'espace mise à jour"));
  const open = useWpMutation((s: string[]) => wp.openSections(w.id, s), () => toast("Espace des mariés mis à jour"));
  if (isLoading || !data) return <Loading />;
  return (
    <div>
      <Section title="Compte du couple">
        <div className="two">
          {data.partners.map((p) => {
            const [cls, label] = STATUS[p.status] ?? ["", p.status];
            return (
              <div key={p.index}>
                <div className="kicker">{p.first_name || `Partenaire ${p.index + 1}`}</div>
                <div>{p.email ?? "E-mail à renseigner dans la fiche"}</div>
                <span className={`pill ${cls}`}>{label}</span>
                {p.email && p.status !== "accepted" && (
                  <div style={{ marginTop: 8 }}>
                    <button className="btn ghost small" onClick={() => invite.mutate(p.index, { onError: (e) => toast(e.message) })}>
                      {p.status === "pending" ? "Renvoyer l'invitation" : "Envoyer l'invitation"}
                    </button>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </Section>
      <Section title="Langue de l'espace du couple">
        <p>Choisie à la création du compte. Tout l'espace s'adapte : menus, textes, formulaires et e-mails.</p>
        <select value={data.lang} aria-label="Langue de l'espace des mariés" onChange={(e) => lang.mutate(e.target.value)}>
          <option value="fr">Français</option><option value="en">Anglais</option>
        </select>
      </Section>
      <Section title="Ce que le couple peut voir">
        {RIGHTS.map(([k, l]) => (
          <label key={k} className="tog"><span>{l}</span>
            <input type="checkbox" checked={data.rights[k]} onChange={(e) => rights.mutate({ ...data.rights, [k]: e.target.checked })} />
          </label>
        ))}
      </Section>
      <Section title="Rubriques ouvertes dans l'espace des mariés">
        <p className="muted">Accueil, informations et questionnaire sont toujours ouverts. Les autres rubriques s'ouvrent au fil de l'organisation.</p>
        {SECTIONS.map(([k, l]) => {
          const available = data.available_sections.includes(k);
          return (
            <label key={k} className="tog"><span>{l}{!available && <span className="kicker"> · bientôt</span>}</span>
              <input type="checkbox" disabled={!available} checked={data.open_sections.includes(k)}
                     onChange={(e) => open.mutate(e.target.checked ? [...data.open_sections, k] : data.open_sections.filter((x) => x !== k))} />
            </label>
          );
        })}
      </Section>
    </div>
  );
}

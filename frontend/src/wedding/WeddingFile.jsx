import { useEffect, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { useMe } from "@/context/MeContext";
import { download, fmtDate, Loading, num, Section, send, toast, useWm, useWq, Wp } from "./core";
import { InfoForm } from "./InfoForm";

const TABS = [["info", "Informations"], ["events", "Événements"], ["quest", "Questionnaire"], ["food", "Repas et boissons"], ["recap", "Récapitulatif"], ["access", "Compte et droits"]];
const B = (id) => `/wedding/weddings/${id}`;

function EventsTab({ w }) {
  const [events, setEvents] = useState(w.events);
  useEffect(() => setEvents(w.events), [w.events]);
  const save = useWm((e) => send("put", `${B(w.id)}/events`, { events: e }), () => toast("Événements enregistrés, visibles aussi dans Événements"));
  const set = (i, p) => setEvents((xs) => xs.map((x, j) => (j === i ? { ...x, ...p } : x)));
  const named = (e) => e.key.startsWith("x");
  return (
    <div>
      <div className="note">Choisissez les événements de ce mariage. Chaque événement activé et daté apparaît dans Événements (devis, DJ, logistique, espace client). Le questionnaire, Repas et boissons, et plus tard la Guest List, la musique et le planning ne montrent que les événements activés.</div>
      {events.map((ev, i) => (
        <div key={ev.id} className="sec" style={ev.enabled ? undefined : { opacity: 0.55 }}>
          <div className="row spread">
            <label className="row"><input type="checkbox" checked={ev.enabled} disabled={ev.fixed} aria-label={`Activer ${ev.name}`} onChange={(e) => set(i, { enabled: e.target.checked })} /><span className="strong">{ev.fixed ? "Toujours actif" : ev.enabled ? "Activé" : "Désactivé"}</span></label>
            <div className="row">{ev.event_id && <Link className="btn ghost small" to={`/evenements/${ev.event_id}`}>Voir l'événement</Link>}{named(ev) && <button className="btn ghost small" onClick={() => setEvents(events.filter((_, j) => j !== i))}>Supprimer</button>}</div>
          </div>
          <label className="l">Nom</label><input value={ev.name} disabled={!named(ev)} onChange={(e) => set(i, { name: e.target.value })} aria-label="Nom de l'événement" />
          <div className="two">
            <div><label className="l">Date</label><input type="date" value={ev.date ?? ""} onChange={(e) => set(i, { date: e.target.value || null })} /></div>
            <div><label className="l">Invités, estimation</label><input inputMode="numeric" value={ev.estimate ?? ""} onChange={(e) => set(i, { estimate: num(e.target.value) })} /></div>
          </div>
          <div className="row" style={{ marginTop: 10 }}>{ev.confirmed ? <span className="pill ok">Confirmés dans la Guest List : {ev.confirmed}</span> : <span className="pill">Guest List : aucun invité encore ajouté</span>}<span className="kicker">{ev.confirmed ? "Ce nombre se met à jour tout seul" : "On garde l'estimation en attendant"}</span></div>
          <label className="l">Lieu</label><input value={ev.place} onChange={(e) => set(i, { place: e.target.value })} />
        </div>
      ))}
      <div className="row" style={{ marginTop: 16 }}>
        <button className="btn ghost" onClick={() => { const id = Math.random().toString(36).slice(2, 10); setEvents([...events, { id, key: `x${id}`, name: "Autre événement", enabled: true, fixed: false, date: null, place: "", estimate: null }]); }}>Ajouter un événement « Autre »</button>
        <button className="btn" disabled={save.isPending} onClick={() => save.mutate(events)}>Enregistrer</button>
      </div>
    </div>
  );
}

const LABELS = { budget: "Budget global", "guests.adults": "Adultes", "guests.kids": "Enfants", "ceremony.type": "Type de cérémonie", "ceremony.place": "Lieu de la cérémonie",
  "ceremony.time": "Horaire de la cérémonie", "ceremony.confession": "Confession", "partners.0.job": "Profession, partenaire 1", "partners.1.job": "Profession, partenaire 2" };

function QuestionnaireTab({ w }) {
  const { data } = useWq(["quest", w.id], `${B(w.id)}/questionnaire`);
  const resolve = useWm(({ id, keep }) => send("post", `${B(w.id)}/discrepancies/${encodeURIComponent(id)}/resolve`, { keep }), () => toast("Fiche mise à jour"));
  if (!data) return <Loading />;
  const answered = data.sections.reduce((n, s) => n + s.answered, 0);
  return (
    <div>
      <div className="row">
        {data.status === "submitted" ? <span className="pill ok">Rempli{data.submitted_at ? ` le ${new Date(data.submitted_at).toLocaleDateString("fr-FR", { day: "numeric", month: "long" })}` : ""}</span> : <span className="pill">En attente</span>}
        <span className={`pill${data.connected ? "" : " warn"}`}>{data.connected ? "Google Form connecté" : "Google Form non connecté"}</span>
        {!data.connected && <Link to="/mariages/reglages">Connecter le formulaire</Link>}
      </div>
      <div className="note">Les réponses du Google Form existant arrivent ici automatiquement, rangées par section. Aucune question à recréer.</div>
      {data.discrepancies.length > 0 && (
        <div className="sec"><h3>Différences détectées</h3><p className="muted">La fiche est la référence : rien n'a été écrasé. Choisissez la valeur à garder.</p>
          {data.discrepancies.map((d) => (
            <div key={d.id} className="qa"><div className="q">{LABELS[d.field] ?? d.field} · {d.question}</div>
              <div className="row"><span>Fiche : <b className="strong">{String(d.fiche_value)}</b></span><span>Formulaire : <b className="strong">{String(d.form_value)}</b></span>
                <button className="btn ghost small" onClick={() => resolve.mutate({ id: d.id, keep: "fiche" })}>Garder la fiche</button><button className="btn small" onClick={() => resolve.mutate({ id: d.id, keep: "form" })}>Prendre le formulaire</button></div></div>
          ))}
        </div>
      )}
      {answered === 0 && <div className="empty"><h3>Aucune réponse pour le moment</h3><p>Dès que le couple remplit le formulaire, ses réponses s'affichent ici.</p></div>}
      {data.sections.filter((s) => s.answered > 0).map((s, i) => (
        <details key={s.title + i} className="sec" open={i < 2}>
          <summary><h3>{s.title} <span className="kicker">({s.answered} réponses)</span></h3></summary>
          {s.questions.filter((q) => q.answer).map((q) => (
            <div key={q.id} className="qa"><div className="q">{q.title}</div><div style={{ whiteSpace: "pre-wrap" }}>{q.answer}</div>
              {q.files.length > 0 && <div className="row files">{q.files.map((f) => <a key={f.url} href={f.url} target="_blank" rel="noreferrer">{f.name}</a>)}</div>}
              <div className="row" style={{ marginTop: 4 }}>{q.deleted && <span className="pill warn">Question supprimée</span>}{q.to_classify && <span className="pill warn">À classer</span>}{q.modified_in_fiche && <span className="pill">Modifié dans la fiche</span>}</div></div>
          ))}
        </details>
      ))}
    </div>
  );
}

const UNITS = { bottle: "bouteilles", keg: "fûts", l: "litres" };
const EMPTY = { vendor: "", formula: "", price: "", notes: "", courses: [{ name: "Plat", chosen: "", options: [] }], included: [], external: [] };

function FoodTab({ w }) {
  const events = w.events.filter((e) => e.enabled);
  const [key, setKey] = useState(events.find((e) => e.key === "dj")?.key ?? events[0]?.key);
  const { data } = useWq(["food", w.id, key], `${B(w.id)}/food/${key}`, { enabled: !!key });
  const [f, setF] = useState(null);
  useEffect(() => setF(data?.food ?? null), [data]);
  const save = useWm((x) => send("put", `${B(w.id)}/food/${key}`, x), () => toast("Repas et boissons enregistrés"));
  const g = data?.guests ?? null;
  const upd = (p) => setF((x) => (x ? { ...x, ...p } : x));
  const list = (k, i, p) => upd({ [k]: f[k].map((x, j) => (j === i ? { ...x, ...p } : x)) });
  return (
    <div>
      <div className="note">Vous modifiez ici ce que les mariés voient dans « Repas et boissons ». Les notes internes ne sont jamais visibles par le couple.{!w.open_sections.includes("food") && " Cette rubrique n'est pas encore ouverte dans l'espace du couple (Compte et droits)."}</div>
      <div className="row" style={{ margin: "14px 0" }}>{events.map((e) => <button key={e.key} className={`btn${key === e.key ? "" : " ghost"}`} onClick={() => setKey(e.key)}>{e.name}</button>)}</div>
      {!data ? <Loading /> : (
        <>
          <div className="kicker">{data.event.name} · {g ?? "?"} invités ({data.guests_source === "guest_list" ? "Guest List" : "estimation"})</div>
          <Section kicker="Prestataire rattaché à cet événement">
            {f ? <div className="two"><div><label className="l">Prestataire</label><input value={f.vendor} onChange={(e) => upd({ vendor: e.target.value })} /></div><div className="row" style={{ alignItems: "end" }}><button className="btn ghost small" onClick={() => save.mutate({ ...f, vendor: "" })}>Détacher ce traiteur</button></div></div>
              : <div className="row" style={{ marginTop: 8 }}><span>Aucun prestataire validé. Les mariés voient « Choisissez d'abord votre traiteur ».</span><button className="btn" onClick={() => setF({ ...EMPTY })}>Rattacher un traiteur</button></div>}
            <div className="note" style={{ marginTop: 12 }}>Les prestataires proposés viendront de votre catalogue (phase 3). En attendant, saisissez le nom du traiteur validé.</div>
          </Section>
          {f && (<>
            <Section><div className="two"><div><label className="l">Formule</label><input value={f.formula} onChange={(e) => upd({ formula: e.target.value })} /></div><div><label className="l">Prix</label><input value={f.price ?? ""} onChange={(e) => upd({ price: e.target.value })} /></div></div></Section>
            <Section title="Menu">
              {f.courses.map((c, i) => (
                <div key={i} className="qa">
                  <div className="two"><div><label className="l">Service</label><input value={c.name} onChange={(e) => list("courses", i, { name: e.target.value })} /></div><div><label className="l">Choix retenu</label><input value={c.chosen} onChange={(e) => list("courses", i, { chosen: e.target.value })} /></div></div>
                  <label className="l">Options proposées</label><input value={c.options.join(", ")} placeholder="Options séparées par une virgule" onChange={(e) => list("courses", i, { options: e.target.value.split(",").map((s) => s.trim()).filter(Boolean) })} />
                  <button className="btn ghost small" style={{ marginTop: 8 }} onClick={() => upd({ courses: f.courses.filter((_, j) => j !== i) })}>Retirer ce service</button>
                </div>
              ))}
              <button className="btn ghost" onClick={() => upd({ courses: [...f.courses, { name: "Nouveau service", chosen: "", options: [] }] })}>Ajouter un service</button>
            </Section>
            <Section title="Boissons incluses">
              {f.included.map((d, i) => <div key={i} className="two qa"><input value={d.name} aria-label="Boisson incluse" onChange={(e) => list("included", i, { name: e.target.value })} /><div className="row"><input value={d.detail} style={{ flex: 1 }} aria-label="Détail" onChange={(e) => list("included", i, { detail: e.target.value })} /><button className="btn ghost small" onClick={() => upd({ included: f.included.filter((_, j) => j !== i) })}>Retirer</button></div></div>)}
              <button className="btn ghost" onClick={() => upd({ included: [...f.included, { name: "Nouvelle boisson", detail: "" }] })}>Ajouter une boisson incluse</button>
            </Section>
            <Section title="Boissons d'un autre fournisseur">
              <div className="tablewrap"><table><thead><tr><th>Boisson</th><th>Fournisseur</th><th>Par invité</th><th>Unité</th><th>Quantité à commander</th><th /></tr></thead>
                <tbody>{f.external.map((d, i) => (
                  <tr key={i}><td><input value={d.name} aria-label="Boisson" onChange={(e) => list("external", i, { name: e.target.value })} /></td><td><input value={d.supplier} aria-label="Fournisseur" onChange={(e) => list("external", i, { supplier: e.target.value })} /></td>
                    <td><input type="number" step="0.1" min="0" value={d.per_guest} style={{ width: 80 }} aria-label="Par invité" onChange={(e) => list("external", i, { per_guest: parseFloat(e.target.value) || 0 })} /></td>
                    <td><select value={d.unit} aria-label="Unité" onChange={(e) => list("external", i, { unit: e.target.value })}>{Object.entries(UNITS).map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select></td>
                    <td className="num">{g == null ? "?" : `${Math.ceil(g * d.per_guest)} ${UNITS[d.unit]}`}</td><td><button className="btn ghost small" onClick={() => upd({ external: f.external.filter((_, j) => j !== i) })}>Retirer</button></td></tr>
                ))}</tbody></table></div>
              <button className="btn ghost" style={{ marginTop: 10 }} onClick={() => upd({ external: [...f.external, { name: "Nouvelle boisson", supplier: "", per_guest: 0.3, unit: "bottle" }] })}>Ajouter une boisson</button>
            </Section>
          </>)}
          <Section title="Contraintes alimentaires de cet événement" kicker="Calculées depuis la Guest List">
            <p className="muted">Elles s'afficheront ici dès que la Guest List sera ouverte (régimes et allergies saisis par invité).</p>
            {data.food && <button className="btn ghost" style={{ marginTop: 10 }} onClick={() => download(`${B(w.id)}/food/${key}/pdf`, `traiteur-${key}.pdf`).then(() => toast("Fiche traiteur téléchargée"))}>Exporter pour le traiteur (PDF)</button>}
          </Section>
          {f && <Section title="Notes internes"><span className="pill warn">Invisible pour les mariés</span><textarea style={{ marginTop: 10 }} value={f.notes ?? ""} aria-label="Notes internes" onChange={(e) => upd({ notes: e.target.value })} /></Section>}
          {f && <div className="row" style={{ marginTop: 18 }}><button className="btn" disabled={save.isPending || !f.vendor} onClick={() => save.mutate(f)}>Enregistrer</button></div>}
        </>
      )}
    </div>
  );
}

function Rubric({ w, r }) {
  const [text, setText] = useState(r.text);
  useEffect(() => setText(r.text), [r.text]);
  const edit = useWm((t) => send("patch", `${B(w.id)}/recap/${r.key}`, { text: t }), () => toast("Passage enregistré, il sera conservé si vous régénérez"));
  const prop = useWm((accept) => send("post", `${B(w.id)}/recap/${r.key}/proposal?accept=${accept}`));
  return (
    <div className="sec">
      <div className="row spread"><h3>{r.title}</h3>{r.edited && <span className="pill">Modifié à la main</span>}</div>
      <textarea aria-label={r.title} value={text} onChange={(e) => setText(e.target.value)} onBlur={() => text !== r.text && edit.mutate(text)} placeholder="Rien à signaler pour le moment." />
      {r.proposal && <div className="proposal"><div className="kicker">Nouvelle version proposée depuis les dernières réponses</div>{r.proposal}
        <div className="row" style={{ marginTop: 8 }}><button className="btn small" onClick={() => prop.mutate(true)}>Remplacer ma version</button><button className="btn ghost small" onClick={() => prop.mutate(false)}>Garder ma version</button></div></div>}
    </div>
  );
}

function RecapTab({ w }) {
  const { data } = useWq(["recap", w.id], `${B(w.id)}/recap`);
  const gen = useWm(() => send("post", `${B(w.id)}/recap/generate`), () => toast("Récapitulatif régénéré (les passages modifiés à la main sont conservés)"));
  if (!data) return <Loading />;
  return (
    <div>
      <div className="row">
        {data.generated_at && <span className="pill ok">Généré depuis le questionnaire</span>}
        <button className="btn ghost" disabled={gen.isPending} onClick={() => gen.mutate()}>{gen.isPending ? "Génération…" : data.generated_at ? "Régénérer" : "Générer le récapitulatif"}</button>
        {data.generated_at && <button className="btn ghost" onClick={() => download(`${B(w.id)}/recap/pdf`, "recapitulatif.pdf").then(() => toast("PDF téléchargé"))}>Télécharger le PDF</button>}
      </div>
      <div className="note">Synthèse modifiable : l'essentiel sans relire tout le questionnaire. Vos corrections sont gardées si vous régénérez. Les mariés ne voient jamais ce récapitulatif.</div>
      {!data.generated_at && <div className="empty"><h3>Pas encore de récapitulatif</h3><p>Générez-le dès que le couple a rempli son questionnaire.</p></div>}
      {data.rubrics.map((r) => <Rubric key={r.key} w={w} r={r} />)}
    </div>
  );
}

const RIGHTS = [["budget", "Budget global visible par les mariés"], ["vendor_prices", "Tarifs des prestataires visibles"], ["dday_planning", "Planning du jour J visible"], ["documents", "Documents partagés visibles"], ["edit_info", "Les mariés peuvent modifier la fiche informations"]];
const SECTIONS = [["food", "Repas et boissons"], ["vendors", "Nos prestataires"], ["guests", "Guest list"], ["seating", "Plan de table"], ["budget", "Budget et paiements"], ["group_photos", "Photos de groupe"], ["music", "Musiques"], ["design", "Design et ambiance"], ["planning", "Planning"], ["documents", "Récapitulatif et documents"]];
const STATUS = { accepted: ["ok", "Invité, connecté"], pending: ["warn", "Invitation envoyée"], not_invited: ["", "Pas encore invité"], suspended: ["warn", "Accès suspendu"] };

function AccountTab({ w }) {
  const { data } = useWq(["account", w.id], `${B(w.id)}/account`);
  const [link, setLink] = useState(null);
  const invite = useWm((i) => send("post", `${B(w.id)}/invite/${i}`), (r) => (r.link ? setLink(r.link) : toast("Invitation envoyée")));
  const rights = useWm((r) => send("put", `${B(w.id)}/rights`, r), () => toast("Droit mis à jour"));
  const lang = useWm((l) => send("put", `${B(w.id)}/lang`, { lang: l }), () => toast("Langue de l'espace mise à jour"));
  const open = useWm((s) => send("put", `${B(w.id)}/open-sections`, { open_sections: s }), () => toast("Espace des mariés mis à jour"));
  if (!data) return <Loading />;
  return (
    <div>
      <Section title="Compte du couple">
        <div className="two">{data.partners.map((p) => { const [cls, label] = STATUS[p.status] ?? ["", p.status]; return (
          <div key={p.index}><div className="kicker">{p.first_name || `Partenaire ${p.index + 1}`}</div><div>{p.email ?? "E-mail à renseigner dans la fiche"}</div><span className={`pill ${cls}`}>{label}</span>
            {p.email && p.status !== "accepted" && <div style={{ marginTop: 8 }}><button className="btn ghost small" onClick={() => invite.mutate(p.index)}>{p.status === "pending" ? "Renvoyer l'invitation" : "Envoyer l'invitation"}</button></div>}</div>); })}</div>
        {link && <div className="note">E-mail non envoyé automatiquement (messagerie non connectée ou hors production). Lien personnel à transmettre : <input readOnly value={link} onFocus={(e) => e.target.select()} style={{ marginTop: 6 }} /></div>}
      </Section>
      <Section title="Langue de l'espace du couple"><p>Tout l'espace s'adapte : menus, textes, formulaires et e-mails.</p>
        <select value={data.lang} aria-label="Langue de l'espace des mariés" onChange={(e) => lang.mutate(e.target.value)}><option value="fr">Français</option><option value="en">Anglais</option></select></Section>
      <Section title="Ce que le couple peut voir">{RIGHTS.map(([k, l]) => <label key={k} className="tog"><span>{l}</span><input type="checkbox" checked={data.rights[k]} onChange={(e) => rights.mutate({ ...data.rights, [k]: e.target.checked })} /></label>)}</Section>
      <Section title="Rubriques ouvertes dans l'espace des mariés"><p className="muted">Accueil, informations et questionnaire sont toujours ouverts. Les autres rubriques s'ouvrent au fil de l'organisation.</p>
        {SECTIONS.map(([k, l]) => { const ok = data.available_sections.includes(k); return (
          <label key={k} className="tog"><span>{l}{!ok && <span className="kicker"> · bientôt</span>}</span><input type="checkbox" disabled={!ok} checked={data.open_sections.includes(k)} onChange={(e) => open.mutate(e.target.checked ? [...data.open_sections, k] : data.open_sections.filter((x) => x !== k))} /></label>); })}</Section>
    </div>
  );
}

export default function WeddingFile() {
  const { id } = useParams();
  const nav = useNavigate();
  const [sp, setSp] = useSearchParams();
  const tab = sp.get("onglet") || "info";
  const { can } = useMe();
  const { data: w, isLoading, error } = useWq(["wedding", id], B(id));
  const save = useWm((info) => send("put", `${B(id)}/info`, info), () => toast("Enregistré. Le récapitulatif, les contacts et les événements se mettent à jour."));
  return (
    <Wp>
      <button className="back" onClick={() => nav("/mariages")}>← Tous les mariages</button>
      {isLoading && <Loading />}
      {error && <p>Mariage introuvable.</p>}
      {w && (<>
        <div className="kicker">{w.info.date ? `${fmtDate(w.info.date)} · ${w.days_left} jours` : "Date à définir"}</div>
        <h1>{w.names}</h1>
        <div className="row" style={{ margin: "16px 0" }} role="tablist">
          {TABS.map(([k, l]) => <button key={k} role="tab" aria-selected={tab === k} className={`btn${tab === k ? "" : " ghost"}`} onClick={() => setSp({ onglet: k }, { replace: true })} data-testid={`wedding-tab-${k}`}>{l}{k === "quest" && w.discrepancies.length > 0 ? ` (${w.discrepancies.length})` : ""}</button>)}
        </div>
        {tab === "info" && <><div className="note">Les mariés complètent cette fiche de leur côté. Vous pouvez aussi la modifier. Une seule saisie : elle alimente les contacts, les événements, le récapitulatif et les autres onglets.</div>
          <InfoForm info={w.info} lang="fr" admin canEdit={can("events:write")} saving={save.isPending} onSave={(info) => save.mutate(info)} /></>}
        {tab === "events" && <EventsTab w={w} />}
        {tab === "quest" && <QuestionnaireTab w={w} />}
        {tab === "food" && <FoodTab w={w} />}
        {tab === "recap" && <RecapTab w={w} />}
        {tab === "access" && <AccountTab w={w} />}
      </>)}
    </Wp>
  );
}

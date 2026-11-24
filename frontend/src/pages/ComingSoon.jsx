import { Hourglass } from "lucide-react";
import { PageHeader, EmptyState } from "@/components/common";

const INFO = {
  chargement: ["Chargement du jour", "Liste automatique du matériel à charger par événement et par véhicule, check-list mobile et signalement des manquants."],
  livraison: ["Livraison", "Tournées du jour, itinéraire, bons de livraison/retour avec signature électronique et photos."],
  "devis-factures": ["Devis & factures", "Création depuis l'événement, lignes du catalogue, TVA, acomptes, PDF, numérotation et transformation devis → facture."],
  "notes-de-frais": ["Notes de frais", "Saisie avec photo du justificatif, rattachement à un événement et validation."],
  entrepots: ["Entrepôts & stocks", "Plusieurs entrepôts, stock par emplacement et transferts : prévu à l'étape suivante (prompt 8). Le stock actuel reste géré dans Catalogue produits."],
  compta: ["Compta", "Encaissements, impayés, rentabilité par événement et export CSV."],
  commercial: ["Commercial", "Pipeline des opportunités, taux de conversion et relances."],
  documents: ["Documents", "Modèles (devis, contrats, fiches techniques) et stockage des fichiers par événement."],
  ecrans: ["Écrans TV", "Vues plein écran du dépôt : chargements, livraisons du jour et planning de la semaine."],
  prestataires: ["Prestataires", "Sociétés, métiers, tarifs, zones, documents (assurance, Kbis) et évaluations."],
};

export default function ComingSoon({ slug }) {
  const [title, text] = INFO[slug] || ["Bientôt", ""];
  return (
    <div>
      <PageHeader eyebrow="Prochaine étape" title={title} />
      <EmptyState icon={Hourglass} title="Module prévu dans une prochaine étape" text={text} />
    </div>
  );
}

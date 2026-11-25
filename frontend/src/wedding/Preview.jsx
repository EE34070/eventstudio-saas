import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { errMsg } from "@/lib/api";
import CoupleSpace from "./CoupleSpace";
import { get, Loading, setPreview, Wp } from "./core";

/** « Voir comme les mariés » : l'espace du couple tel qu'il le voit (mêmes droits, rubriques ouvertes, langue), en lecture seule. */
export default function WeddingPreview() {
  const { id } = useParams();
  const [home, setHome] = useState(null);
  const [error, setError] = useState(null);
  useEffect(() => {
    setPreview(id);
    setHome(null);
    get("/portal/wedding").then(setHome).catch((e) => setError(errMsg(e)));
    return () => setPreview(null);
  }, [id]);
  const back = `/mariages/${id}?onglet=access`;
  return (
    <div data-testid="wedding-preview">
      <div className="wp" style={{ position: "sticky", top: 0, zIndex: 20 }}>
        <div className="row spread" style={{ background: "#1F3D2B", color: "#F2F1EB", padding: "10px 18px", fontSize: 13 }}>
          <span><strong>Aperçu</strong> · vous voyez exactement ce que voient {home?.names || "les mariés"}. Rien n'est modifiable ici.</span>
          <Link to={back} style={{ color: "#F2F1EB", textDecoration: "underline" }}>Retour au dossier</Link>
        </div>
      </div>
      {error ? <Wp><div className="empty"><h3>Aperçu indisponible</h3><p>{error}</p><Link className="btn" to={back}>Retour au dossier</Link></div></Wp>
        : home ? <CoupleSpace home={home} /> : <Wp><Loading /></Wp>}
    </div>
  );
}

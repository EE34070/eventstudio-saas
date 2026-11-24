import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { Upload, X, FileText } from "lucide-react";
import { Button } from "@/components/ui/button";
import { api, errMsg } from "@/lib/api";

const blobUrl = async (ref) => URL.createObjectURL((await api.get(`/files/${ref.slice(5)}`, { responseType: "blob" })).data);

export function FileImg({ src, alt = "", className = "", ...p }) {
  const [url, setUrl] = useState("");
  useEffect(() => {
    if (!src?.startsWith("file:")) { setUrl(src || ""); return undefined; }
    let off = false;
    let u;
    blobUrl(src).then((x) => { u = x; if (!off) setUrl(x); }).catch(() => {});
    return () => { off = true; if (u) URL.revokeObjectURL(u); };
  }, [src]);
  return url ? <img src={url} alt={alt} className={className} {...p} /> : <div className={`${className} bg-secondary`} />;
}

export const openFile = async (ref) => {
  try {
    if (!ref.startsWith("file:")) { window.open(ref, "_blank", "noopener"); return; }
    const { data } = await api.get(`/files/${ref.slice(5)}/link`);
    window.open(data.url || (await blobUrl(ref)), "_blank", "noopener");
  } catch { toast.error("Fichier introuvable"); }
};

export function UploadButton({ onUploaded, accept = "image/*,application/pdf", label = "Téléverser", testid, multiple = true }) {
  const input = useRef(null);
  const [busy, setBusy] = useState(false);
  const pick = async (e) => {
    const files = [...e.target.files];
    e.target.value = "";
    setBusy(true);
    const refs = [];
    for (const file of files) {
      const fd = new FormData();
      fd.append("file", file);
      try { refs.push((await api.post("/files", fd)).data.ref); } catch (err) { toast.error(`${file.name} : ${errMsg(err)}`); }
    }
    setBusy(false);
    if (refs.length) onUploaded(refs);
  };
  return (
    <>
      <input ref={input} type="file" hidden accept={accept} multiple={multiple} onChange={pick} data-testid={testid ? `${testid}-input` : undefined} />
      <Button type="button" size="sm" disabled={busy} onClick={() => input.current.click()} data-testid={testid}><Upload />{busy ? "Envoi…" : label}</Button>
    </>
  );
}

export function FileList({ label, value, onChange, testid, readOnly }) {
  return (
    <div className="col-span-2" data-testid={testid}>
      <div className="mb-2 flex items-center justify-between gap-2">
        <span className="text-xs font-medium text-muted-foreground">{label} ({value.length})</span>
        {!readOnly && <UploadButton testid={`${testid}-upload`} onUploaded={(refs) => onChange([...value, ...refs])} />}
      </div>
      <div className="flex flex-wrap gap-2">
        {value.map((ref, i) => (
          <div key={ref + i} className="relative h-20 w-20 overflow-hidden rounded-xl border border-border">
            <button type="button" className="h-full w-full" onClick={() => openFile(ref)} title="Ouvrir">
              <FileImg src={ref} className="h-full w-full object-cover" />
              <FileText className="absolute left-1 top-1 h-4 w-4 opacity-40" />
            </button>
            {!readOnly && <button type="button" onClick={() => onChange(value.filter((_, j) => j !== i))} className="absolute right-1 top-1 rounded-full bg-background/90 p-0.5" aria-label="Retirer"><X className="h-3.5 w-3.5" /></button>}
          </div>
        ))}
      </div>
    </div>
  );
}

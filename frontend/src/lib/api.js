import axios from "axios";

export const api = axios.create({ baseURL: `${process.env.REACT_APP_BACKEND_URL}/api` });

const viewAs = sessionStorage.getItem("view-as-member");
if (viewAs) api.defaults.headers.common["X-View-As-Member"] = viewAs;

let tokenGetter = null;
export const setTokenGetter = (fn) => { tokenGetter = fn; };

api.interceptors.request.use(async (cfg) => {
  if (tokenGetter) {
    const t = await tokenGetter();
    if (t) cfg.headers.Authorization = `Bearer ${t}`;
  }
  return cfg;
});

export const errMsg = (e) => {
  const d = e?.response?.data?.detail;
  if (typeof d === "string") return d;
  if (d?.message) return d.message;
  if (Array.isArray(d)) return "Champs invalides : " + d.map((x) => x.loc?.slice(-1)[0]).join(", ");
  return "Une erreur est survenue";
};

export const downloadPdf = async (path, filename) => {
  const r = await api.get(path, { responseType: "blob" });
  const url = URL.createObjectURL(r.data);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 5000);
};

export const conflictsOf = (e) => e?.response?.data?.detail?.conflicts || null;

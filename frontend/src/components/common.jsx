import { statusLabel, moduleLabel } from "@/lib/constants";
import { Loader2, Search } from "lucide-react";

export const StatusBadge = ({ status, testid }) => (
  <span data-testid={testid} className={`st-${status} inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-[11px] font-semibold tracking-wide whitespace-nowrap`}>
    <span className={`dot-${status} h-1.5 w-1.5 rounded-full`} />
    {statusLabel(status)}
  </span>
);

export const ModuleBadge = ({ module }) => (
  <span className="inline-flex rounded-md border border-border bg-secondary px-1.5 py-0.5 text-[10.5px] font-medium text-secondary-foreground">{moduleLabel(module)}</span>
);

export const PageHeader = ({ title, subtitle, actions }) => (
  <div className="mb-8 flex flex-wrap items-start justify-between gap-4 fade-up">
    <div className="min-w-0">
      <h1 className="text-4xl font-extrabold tracking-tight text-foreground sm:text-[40px]" data-testid="page-title">{title}</h1>
      {subtitle && <p className="mt-2 max-w-2xl text-base text-muted-foreground" data-testid="page-subtitle">{subtitle}</p>}
    </div>
    {actions && <div className="flex flex-wrap items-center gap-2 pt-1">{actions}</div>}
  </div>
);

export const Meta = ({ icon: Icon, children, testid }) => (
  <span className="inline-flex items-center gap-1.5 text-[13px] text-[#737373]" data-testid={testid}><Icon className="h-[18px] w-[18px]" />{children}</span>
);

export const SearchPill = ({ value, onChange, placeholder, testid, className = "md:w-1/2" }) => (
  <div className={`relative w-full ${className}`}>
    <Search className="pointer-events-none absolute left-4 top-1/2 h-[18px] w-[18px] -translate-y-1/2 text-[#737373]" />
    <input className="pill-input" value={value} onChange={(e) => onChange(e.target.value)} placeholder={placeholder} data-testid={testid} />
  </div>
);

export const EmptyState = ({ icon: Icon, title, text, action }) => (
  <div className="flex flex-col items-center justify-center rounded-2xl border border-dashed border-border bg-card px-6 py-14 text-center">
    {Icon && <div className="mb-4 rounded-full bg-accent p-3 text-accent-foreground"><Icon className="h-5 w-5" /></div>}
    <div className="font-medium">{title}</div>
    {text && <p className="mt-1 max-w-sm text-sm text-muted-foreground">{text}</p>}
    {action && <div className="mt-5">{action}</div>}
  </div>
);

export const Loading = () => (
  <div className="flex items-center justify-center py-20 text-muted-foreground" data-testid="loading">
    <Loader2 className="h-5 w-5 animate-spin" />
  </div>
);

export const Section = ({ title, actions, children, className = "", testid }) => (
  <div className={`card-soft p-5 ${className}`} data-testid={testid}>
    {(title || actions) && (
      <div className="mb-4 flex items-center justify-between gap-3">
        {title && <h3 className="text-[15px] font-semibold">{title}</h3>}
        {actions}
      </div>
    )}
    {children}
  </div>
);

export const Field = ({ label, children, className = "" }) => (
  <label className={`flex flex-col gap-1.5 ${className}`}>
    <span className="text-xs font-medium text-muted-foreground">{label}</span>
    {children}
  </label>
);

export const Info = ({ label, value }) => (
  <div>
    <div className="eyebrow mb-1">{label}</div>
    <div className="text-sm">{value || <span className="text-muted-foreground">—</span>}</div>
  </div>
);

import { Children, cloneElement, isValidElement, type ReactElement, type ReactNode } from "react";
import { formatInr } from "./format-inr";

export type Tone = "neutral" | "ok" | "warn" | "danger" | "info";

/** A label above its control, then a hint, then the error. The control sits inside the
 *  label, so clicking the text focuses it and the label is its accessible name. */
export function Field({
  label,
  hint,
  error,
  size,
  children,
}: {
  label: string;
  hint?: string;
  error?: string | null;
  /** "short" for a number, a percentage or a prefix: a short value gets a short input. */
  size?: "short";
  children: ReactNode;
}) {
  const only = Children.count(children) === 1 ? Children.only(children) : null;
  const control =
    error && isValidElement(only)
      ? cloneElement(only as ReactElement<{ "aria-invalid"?: boolean }>, { "aria-invalid": true })
      : children;
  return (
    <label className={size === "short" ? "field short" : "field"}>
      <span className="field-label">{label}</span>
      {control}
      {hint ? <span className="hint">{hint}</span> : null}
      {error ? (
        <span className="field-error" role="alert">
          {error}
        </span>
      ) : null}
    </label>
  );
}

/** A meaningful group. Lists inside are rows with dividers, not more cards. */
export function Card({ title, children }: { title?: string; children: ReactNode }) {
  return (
    <section className="card">
      {title ? <h2>{title}</h2> : null}
      {children}
    </section>
  );
}

/** An error that just happened, announced to screen readers. */
export function ErrorBanner({ message }: { message: string | null }) {
  return message ? (
    <p className="error" role="alert">
      {message}
    </p>
  ) : null;
}

/** A notice that is not an error; `role="status"` so it is announced politely. */
export function Notice({ tone = "warn", children }: { tone?: "warn" | "info"; children: ReactNode }) {
  return (
    <p className={tone === "info" ? "notice" : "banner"} role="status">
      {children}
    </p>
  );
}

/** Text plus a tone, so a status never relies on colour alone. */
export function Badge({ tone = "neutral", children }: { tone?: Tone; children: ReactNode }) {
  return <span className={tone === "neutral" ? "badge" : `badge ${tone}`}>{children}</span>;
}

/** Placeholder shaped like the content, for a list or card that is still loading. `what`
 *  is announced to screen readers. */
export function Skeleton({ what, lines = 3, block = false }: { what: string; lines?: number; block?: boolean }) {
  return (
    <div role="status" aria-busy="true" className="stack">
      <span className="visually-hidden">Loading {what}…</span>
      {Array.from({ length: lines }, (_, i) => (
        <span
          key={i}
          aria-hidden="true"
          className={block ? "skeleton block" : i === lines - 1 ? "skeleton short" : i % 2 ? "skeleton mid" : "skeleton"}
        />
      ))}
    </div>
  );
}

/** What is empty, why, and what to do next. */
export function EmptyState({
  title,
  children,
  action,
}: {
  title: string;
  children?: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className="empty">
      <h2>{title}</h2>
      {children ? <p>{children}</p> : null}
      {action}
    </div>
  );
}

/** Page title, one line of context, and the page's actions. */
export function PageHeader({
  title,
  subtitle,
  actions,
}: {
  title: string;
  subtitle?: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <header className="page-head">
      <div>
        <h1>{title}</h1>
        {subtitle ? <p>{subtitle}</p> : null}
      </div>
      {actions ? <div className="actions">{actions}</div> : null}
    </header>
  );
}

/** Display only: the API sends paise, this shows them the Indian way. */
export function Money({ paise }: { paise: number }) {
  return <span className="money">{formatInr(paise)}</span>;
}

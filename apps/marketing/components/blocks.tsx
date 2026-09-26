import Link from "next/link";
import type { ReactNode } from "react";
import { Icon } from "@restosaas/ui";
import { DEMO_HREF } from "@/lib/site";

/** Kicker label, section title and an optional lede, in the design's section rhythm. */
export function SectionHead({
  label,
  title,
  titleId,
  children,
}: {
  label?: string;
  title: ReactNode;
  titleId: string;
  children?: ReactNode;
}) {
  return (
    <div className="section-head">
      {label ? <span className="label">{label}</span> : null}
      <h2 id={titleId}>{title}</h2>
      {children ? <p>{children}</p> : null}
    </div>
  );
}

/** A check-mark list. */
export function Ticks({ items }: { items: ReactNode[] }) {
  return (
    <ul className="ticks">
      {items.map((item, i) => (
        <li key={i}>
          <Icon name="check" />
          <span>{item}</span>
        </li>
      ))}
    </ul>
  );
}

/** The top of every inner page: kicker, the page's one H1, a lede and the two CTAs. */
export function PageHeader({
  label,
  title,
  children,
  actions = true,
}: {
  label?: string;
  title: string;
  children: ReactNode;
  actions?: boolean;
}) {
  return (
    <section className="page-hero" aria-labelledby="page-title">
      <div className="wrap">
        {label ? <span className="label">{label}</span> : null}
        <h1 id="page-title">{title}</h1>
        <p className="lede">{children}</p>
        {actions ? (
          <div className="hero-actions">
            <Link href={DEMO_HREF} className="btn btn-lg">
              Book a demo
            </Link>
            <Link href="/#how" className="btn btn-lg secondary">
              See how it works
            </Link>
          </div>
        ) : null}
      </div>
    </section>
  );
}

/** Numbered steps (the homepage's "how it works" style), for feature pages. */
export function Steps({ steps }: { steps: { title: string; body: ReactNode }[] }) {
  return (
    <ol className="how-steps">
      {steps.map((s) => (
        <li className="how-step" key={s.title}>
          <div className="how-step-top" aria-hidden="true" />
          <h3>{s.title}</h3>
          <p>{s.body}</p>
        </li>
      ))}
    </ol>
  );
}

/** Benefit cards: a short bold title and one sentence. */
export function Benefits({ items }: { items: { title: string; body: ReactNode }[] }) {
  return (
    <ul className="benefits">
      {items.map((b) => (
        <li key={b.title}>
          <h3>{b.title}</h3>
          <p>{b.body}</p>
        </li>
      ))}
    </ul>
  );
}

/** Copy beside media (a screenshot or a mockup). `reverse` puts the media first on wide screens. */
export function Story({
  label,
  title,
  children,
  media,
  reverse,
}: {
  label?: string;
  title: string;
  children: ReactNode;
  media: ReactNode;
  reverse?: boolean;
}) {
  return (
    <article className={`story${reverse ? " story-reverse" : ""}`}>
      <div className="story-copy">
        {label ? <span className="label">{label}</span> : null}
        <h3>{title}</h3>
        {children}
      </div>
      <div className="story-media">{media}</div>
    </article>
  );
}

/** Descriptive internal links to related pages. */
export function RelatedLinks({ links }: { links: { href: string; label: string }[] }) {
  return (
    <section className="section" aria-labelledby="related-heading">
      <div className="wrap">
        <h2 id="related-heading" className="related-title">
          Related
        </h2>
        <ul className="related-links">
          {links.map((l) => (
            <li key={l.href}>
              <Link href={l.href}>
                <span>{l.label}</span>
                <Icon name="chevron" />
              </Link>
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}

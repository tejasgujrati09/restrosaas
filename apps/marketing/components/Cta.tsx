import Link from "next/link";
import { DEMO_HREF } from "@/lib/site";

export function CtaBand({
  heading,
  body,
  primaryHref = DEMO_HREF,
  primaryLabel = "Book a demo",
  secondaryHref,
  secondaryLabel,
}: {
  heading: string;
  body: string;
  primaryHref?: string;
  primaryLabel?: string;
  secondaryHref?: string;
  secondaryLabel?: string;
}) {
  return (
    <section className="section" aria-labelledby="cta-heading">
      <div className="wrap">
        <div className="cta-band">
          <h2 id="cta-heading">{heading}</h2>
          <p>{body}</p>
          <div className="hero-actions">
            <Link href={primaryHref} className="btn btn-lg">
              {primaryLabel}
            </Link>
            {secondaryHref && secondaryLabel ? (
              <Link href={secondaryHref} className="btn btn-lg secondary">
                {secondaryLabel}
              </Link>
            ) : null}
          </div>
        </div>
      </div>
    </section>
  );
}

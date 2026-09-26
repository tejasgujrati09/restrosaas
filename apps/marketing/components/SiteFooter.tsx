import Link from "next/link";
import { DEMO_HREF, FEATURE_LINKS, OTHER_LINKS, SITE_NAME } from "@/lib/site";
import { TablyMark } from "./TablyMark";

export function SiteFooter() {
  const year = new Date().getFullYear();
  return (
    <footer className="site-foot">
      <div className="wrap foot-grid">
        <div className="foot-brand">
          <Link href="/" className="brand" aria-label={`${SITE_NAME}, home`}>
            <TablyMark />
            <span>{SITE_NAME}</span>
          </Link>
          <p>
            QR table ordering, AI phone ordering, a kitchen ticket queue and staff roles for
            restaurants, bars and cafés in India.
          </p>
        </div>
        <nav aria-label="Product" className="foot-col">
          <p className="label">Product</p>
          <ul>
            {FEATURE_LINKS.map((link) => (
              <li key={link.href}>
                <Link href={link.href}>{link.label}</Link>
              </li>
            ))}
          </ul>
        </nav>
        <nav aria-label="Company" className="foot-col">
          <p className="label">Company</p>
          <ul>
            <li>
              <Link href="/#how">How it works</Link>
            </li>
            {OTHER_LINKS.map((link) => (
              <li key={link.href}>
                <Link href={link.href}>{link.label}</Link>
              </li>
            ))}
            <li>
              <Link href={DEMO_HREF}>Book a demo</Link>
            </li>
          </ul>
        </nav>
      </div>
      <div className="wrap">
        <p className="foot-legal">
          &copy; {year} {SITE_NAME}. Early-stage software, built for venues in India.
        </p>
      </div>
    </footer>
  );
}

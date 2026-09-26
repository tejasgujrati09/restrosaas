import Link from "next/link";
import { DEMO_HREF, FEATURE_LINKS, SITE_NAME } from "@/lib/site";
import { MobileNavToggle } from "./MobileNavToggle";
import { TablyMark } from "./TablyMark";

export function SiteHeader() {
  return (
    <header className="site-head">
      <div className="wrap">
        <Link href="/" className="brand" aria-label={`${SITE_NAME}, home`}>
          <TablyMark />
          <span>{SITE_NAME}</span>
        </Link>
        <nav aria-label="Primary" id="primary-nav" className="site-nav">
          <ul>
            <li className="nav-product">
              <details>
                <summary>Product</summary>
                <ul className="nav-product-menu">
                  {FEATURE_LINKS.map((link) => (
                    <li key={link.href}>
                      <Link href={link.href}>{link.label}</Link>
                    </li>
                  ))}
                </ul>
              </details>
            </li>
            <li>
              <Link href="/#how">How it works</Link>
            </li>
            <li>
              <Link href="/#roles">For your team</Link>
            </li>
            <li>
              <Link href="/pricing">Pricing</Link>
            </li>
            <li>
              <Link href="/about">About</Link>
            </li>
            <li>
              <Link href="/contact">Contact</Link>
            </li>
          </ul>
        </nav>
        <Link href={DEMO_HREF} className="btn head-cta">
          Book a demo
        </Link>
        <MobileNavToggle id="primary-nav" />
      </div>
    </header>
  );
}

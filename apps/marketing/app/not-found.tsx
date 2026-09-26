import type { Metadata } from "next";
import Link from "next/link";
import { SITE_NAME } from "@/lib/site";

export const metadata: Metadata = {
  title: { absolute: `Page not found | ${SITE_NAME}` },
  description: "The page you're looking for doesn't exist.",
  robots: { index: false },
};

export default function NotFound() {
  return (
    <main>
      <div className="wrap not-found">
        <span className="label">404</span>
        <h1>Page not found</h1>
        <p className="lede">The page you&rsquo;re looking for doesn&rsquo;t exist or has moved.</p>
        <div className="hero-actions">
          <Link href="/" className="btn btn-lg">
            Back to home
          </Link>
          <Link href="/contact" className="btn btn-lg secondary">
            Contact us
          </Link>
        </div>
      </div>
    </main>
  );
}

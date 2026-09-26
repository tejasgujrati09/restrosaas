import type { Metadata } from "next";
import { SITE_NAME, SITE_URL } from "./site";

/**
 * Build a page's Metadata from a topic + description, applying the consistent title pattern,
 * matching Open Graph fields and a canonical URL. `path` is the route, e.g. "/qr-ordering".
 */
export function pageMetadata(opts: {
  title: string;
  description: string;
  path: string;
}): Metadata {
  const { title, description, path } = opts;
  const fullTitle = `${title} | ${SITE_NAME}`;
  const url = `${SITE_URL}${path}`;

  return {
    // Absolute, so the root layout's "%s | SITE_NAME" template doesn't append the name twice.
    title: { absolute: fullTitle },
    description,
    alternates: {
      canonical: url,
    },
    openGraph: {
      title: fullTitle,
      description,
      url,
      siteName: SITE_NAME,
      type: "website",
    },
  };
}

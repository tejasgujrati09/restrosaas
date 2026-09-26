import type { MetadataRoute } from "next";
import { SITE_INDEXABLE, SITE_URL } from "@/lib/site";

// Production must set NEXT_PUBLIC_SITE_INDEXABLE=true for this to allow crawling. Any other
// deploy (staging/preview/local) leaves it unset and gets a blanket Disallow, so a non-prod
// environment never ends up indexed by accident.
export default function robots(): MetadataRoute.Robots {
  if (!SITE_INDEXABLE) {
    return {
      rules: {
        userAgent: "*",
        disallow: "/",
      },
    };
  }

  return {
    rules: {
      userAgent: "*",
      allow: "/",
    },
    sitemap: `${SITE_URL}/sitemap.xml`,
  };
}

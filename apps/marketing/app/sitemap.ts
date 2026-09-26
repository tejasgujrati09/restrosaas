import type { MetadataRoute } from "next";
import { ALL_ROUTES, SITE_URL } from "@/lib/site";

export default function sitemap(): MetadataRoute.Sitemap {
  return ALL_ROUTES.map((route) => ({
    url: `${SITE_URL}${route.href}`,
    lastModified: new Date(),
    changeFrequency: "monthly",
    priority: route.href === "/" ? 1 : 0.7,
  }));
}

import type { MetadataRoute } from "next";

export default function manifest(): MetadataRoute.Manifest {
  return {
    name: "Order at your table",
    short_name: "Order",
    start_url: "/menu",
    display: "standalone",
    // A manifest cannot use CSS variables: keep these equal to --bg in packages/ui/src/tokens.css.
    background_color: "#f6f1ea",
    theme_color: "#f6f1ea",
  };
}

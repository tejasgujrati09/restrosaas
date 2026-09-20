import type { MetadataRoute } from "next";

export default function manifest(): MetadataRoute.Manifest {
  return {
    name: "Staff",
    short_name: "Staff",
    start_url: "/",
    display: "standalone",
    // A manifest cannot use CSS variables: keep these equal to --bg in packages/ui/src/tokens.css.
    background_color: "#f6f1ea",
    theme_color: "#f6f1ea",
  };
}

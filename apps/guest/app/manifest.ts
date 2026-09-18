import type { MetadataRoute } from "next";

export default function manifest(): MetadataRoute.Manifest {
  return {
    name: "Order at your table",
    short_name: "Order",
    start_url: "/menu",
    display: "standalone",
    background_color: "#ffffff",
    theme_color: "#ffffff",
  };
}

// Central, factual site constants: the brand name, nav, footer and sitemap all come from here.
export const SITE_NAME = "Tably";
export const SITE_TAGLINE =
  "QR table ordering and AI phone ordering for Indian restaurants, bars and cafés, with one Orders screen and one kitchen queue.";

// Placeholder production domain. Replace with the real domain once one is registered; read from
// an env var so canonical/OG URLs and the sitemap/robots host are correct per-deploy.
export const SITE_URL =
  process.env.NEXT_PUBLIC_SITE_URL?.replace(/\/$/, "") ?? "https://www.tably.example";

// Whether this deploy should be indexable by search engines. Defaults to false (non-indexable)
// so a staging/preview deploy never gets crawled by accident — production deploys must set
// NEXT_PUBLIC_SITE_INDEXABLE=true explicitly.
export const SITE_INDEXABLE = process.env.NEXT_PUBLIC_SITE_INDEXABLE === "true";

// Placeholder contact address for the mailto: demo and contact forms. Not a real inbox yet;
// swap for the real one before launch.
export const CONTACT_EMAIL = "hello@tably.example";

export type NavLink = {
  href: string;
  label: string;
  shortLabel: string;
};

// Every real route, used to build nav, footer, sitemap and internal-link copy from one source.
export const FEATURE_LINKS: NavLink[] = [
  { href: "/qr-ordering", label: "QR table ordering", shortLabel: "QR ordering" },
  { href: "/ai-voice-ordering", label: "AI voice ordering", shortLabel: "AI voice ordering" },
  {
    href: "/restaurant-kitchen-management",
    label: "Kitchen ticket queue",
    shortLabel: "Kitchen management",
  },
  {
    href: "/restaurant-staff-management",
    label: "Staff and table assignment",
    shortLabel: "Staff management",
  },
  { href: "/restaurant-analytics", label: "Operational analytics", shortLabel: "Analytics" },
];

export const OTHER_LINKS: NavLink[] = [
  { href: "/pricing", label: "Pricing", shortLabel: "Pricing" },
  { href: "/about", label: "About", shortLabel: "About" },
  { href: "/contact", label: "Contact", shortLabel: "Contact" },
];

export const ALL_ROUTES: NavLink[] = [
  { href: "/", label: "Home", shortLabel: "Home" },
  ...FEATURE_LINKS,
  ...OTHER_LINKS,
];

// Where every "Book a demo" button goes: the demo form at the foot of the homepage.
export const DEMO_HREF = "/#demo";

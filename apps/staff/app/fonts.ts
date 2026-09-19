import localFont from "next/font/local";

// Self-hosted subsets (see packages/ui/fonts/README.md); both include the rupee sign.
const body = localFont({
  src: "../../../packages/ui/fonts/manrope-latin.woff2",
  weight: "500 700",
  variable: "--font-body",
  display: "swap",
});
const display = localFont({
  src: "../../../packages/ui/fonts/fraunces-600-latin.woff2",
  weight: "600",
  variable: "--font-display",
  display: "swap",
  adjustFontFallback: "Times New Roman",
});

export const fontVariables = `${body.variable} ${display.variable}`;

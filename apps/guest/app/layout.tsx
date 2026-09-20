import type { ReactNode } from "react";
import "@restosaas/ui/tokens.css";
import "@restosaas/ui/components.css";
import "./globals.css";
import { fontVariables } from "./fonts";

export const metadata = { title: "Order at your table" };

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en" className={fontVariables}>
      <body>{children}</body>
    </html>
  );
}

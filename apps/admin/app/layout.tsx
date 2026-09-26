import type { ReactNode } from "react";
import { ToastHost } from "@restosaas/ui";
import "@restosaas/ui/tokens.css";
import "@restosaas/ui/components.css";
import "./globals.css";
import { fontVariables } from "./fonts";

export const metadata = { title: "Platform admin" };

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en" className={fontVariables}>
      <body>
        {children}
        <ToastHost />
      </body>
    </html>
  );
}

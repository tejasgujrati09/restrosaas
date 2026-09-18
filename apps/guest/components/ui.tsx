import type { ReactNode } from "react";

export function ErrorBanner({ message }: { message: string | null }) {
  return message ? (
    <p className="error" role="alert">
      {message}
    </p>
  ) : null;
}

export function Loading({ what }: { what: string }) {
  return (
    <p className="muted" role="status">
      Loading {what}…
    </p>
  );
}

export function Card({ children }: { children: ReactNode }) {
  return <section className="card">{children}</section>;
}

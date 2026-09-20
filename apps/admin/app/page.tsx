"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";
import { Skeleton } from "@restosaas/ui";
import { getToken } from "@/lib/session";

/** Signed in: the console. Otherwise: sign in. */
export default function Home() {
  const router = useRouter();
  useEffect(() => {
    router.replace(getToken() ? "/restaurants" : "/login");
  }, [router]);
  return (
    <main className="auth">
      <Skeleton what="the console" lines={2} />
    </main>
  );
}

"use client";

import { useRouter } from "next/navigation";
import { type ReactNode, useEffect } from "react";

import { useAuth } from "@/components/auth-provider";
import { AppShell } from "@/components/shell/app-shell";

export default function AuthenticatedLayout({ children }: { children: ReactNode }) {
  const { user, isLoading } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (!isLoading && !user) router.replace("/login");
  }, [isLoading, user, router]);

  // This guard is a UX affordance, not a security boundary. Every protected
  // resource is enforced server-side by the CurrentUser dependency; bypassing
  // this component would show an empty shell and a wall of 401s.
  if (isLoading || !user) {
    return (
      <div className="grid h-dvh place-items-center">
        <div
          className="size-5 animate-spin rounded-full border-2 border-border border-t-accent"
          role="status"
          aria-label="Loading"
        />
      </div>
    );
  }

  return <AppShell>{children}</AppShell>;
}

"use client";

import { useRouter } from "next/navigation";
import { type ReactNode, useEffect } from "react";

import { useAuth } from "@/components/auth-provider";

export default function AuthLayout({ children }: { children: ReactNode }) {
  const { user, isLoading } = useAuth();
  const router = useRouter();

  // Someone already signed in has no use for the login form.
  useEffect(() => {
    if (!isLoading && user) router.replace("/");
  }, [isLoading, user, router]);

  return (
    <div className="grid min-h-dvh place-items-center px-4 py-12">
      <div className="animate-fade-up w-full max-w-sm">
        <div className="mb-8 flex flex-col items-center gap-3 text-center">
          <span className="grid size-11 place-items-center rounded-xl bg-accent text-accent-contrast">
            <svg viewBox="0 0 24 24" className="size-6" aria-hidden="true">
              <path
                d="M12 3a4 4 0 0 0-4 4v1a3 3 0 0 0 0 6v1a4 4 0 0 0 8 0v-1a3 3 0 0 0 0-6V7a4 4 0 0 0-4-4Z"
                fill="none"
                stroke="currentColor"
                strokeWidth="1.6"
                strokeLinejoin="round"
              />
            </svg>
          </span>
          <h1 className="text-xl font-semibold tracking-tight">SecondBrain AI</h1>
        </div>
        {children}
      </div>
    </div>
  );
}

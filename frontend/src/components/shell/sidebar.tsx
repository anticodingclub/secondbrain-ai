"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { NAV_ITEMS } from "@/lib/navigation";
import { cn } from "@/lib/utils";

export function Sidebar() {
  const pathname = usePathname();

  return (
    <nav
      aria-label="Primary"
      className="hidden w-60 shrink-0 flex-col border-r border-border bg-background-subtle/50 p-3 md:flex"
    >
      <Link
        href="/"
        className="mb-6 flex items-center gap-2.5 px-2 py-1.5 text-sm font-semibold tracking-tight"
      >
        <span className="grid size-7 place-items-center rounded-lg bg-accent text-accent-contrast">
          <svg viewBox="0 0 24 24" className="size-4" aria-hidden="true">
            <path
              d="M12 3a4 4 0 0 0-4 4v1a3 3 0 0 0 0 6v1a4 4 0 0 0 8 0v-1a3 3 0 0 0 0-6V7a4 4 0 0 0-4-4Z"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.6"
              strokeLinejoin="round"
            />
          </svg>
        </span>
        SecondBrain
      </Link>

      <ul className="flex flex-col gap-0.5">
        {NAV_ITEMS.map(({ label, icon: Icon, phase, href }) => {
          if (!href) {
            return (
              <li key={label}>
                <span
                  aria-disabled="true"
                  title={`Arrives in Phase ${phase}`}
                  className="flex cursor-not-allowed items-center gap-3 rounded-sb px-2.5 py-2 text-sm text-subtle/60"
                >
                  <Icon className="size-4" />
                  {label}
                  <span className="ml-auto text-[10px] font-medium tabular-nums text-subtle/70">
                    P{phase}
                  </span>
                </span>
              </li>
            );
          }

          const active = pathname === href;

          return (
            <li key={label}>
              <Link
                href={href}
                aria-current={active ? "page" : undefined}
                className={cn(
                  "flex items-center gap-3 rounded-sb px-2.5 py-2 text-sm transition-colors",
                  active
                    ? "bg-surface text-foreground"
                    : "text-muted hover:bg-surface/60 hover:text-foreground",
                )}
              >
                <Icon className="size-4" />
                {label}
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}

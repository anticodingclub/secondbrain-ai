"use client";

import { LogOut, Search, Settings } from "lucide-react";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";

import { useAuth } from "@/components/auth-provider";
import { useReadiness } from "@/hooks/use-system-info";
import { cn } from "@/lib/utils";

function StatusDot() {
  const { data, isLoading, isError } = useReadiness();

  const state = isLoading
    ? { label: "Connecting", color: "bg-subtle" }
    : isError
      ? { label: "API offline", color: "bg-danger" }
      : data?.status === "ready"
        ? { label: "All systems ready", color: "bg-success" }
        : { label: "Degraded", color: "bg-warning" };

  return (
    <span className="flex items-center gap-2 text-xs text-muted" title={state.label}>
      <span className={cn("size-1.5 rounded-full", state.color)} aria-hidden="true" />
      <span className="hidden sm:inline">{state.label}</span>
    </span>
  );
}

function initialsOf(name: string): string {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase() ?? "")
    .join("");
}

function UserMenu() {
  const { user, logout } = useAuth();
  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;

    function onPointerDown(event: MouseEvent) {
      if (!containerRef.current?.contains(event.target as Node)) setOpen(false);
    }
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") setOpen(false);
    }

    document.addEventListener("mousedown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("mousedown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open]);

  if (!user) return null;

  return (
    <div ref={containerRef} className="relative">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={`Account menu for ${user.display_name}`}
        className="grid size-8 place-items-center rounded-full bg-surface text-xs font-medium text-muted transition-colors hover:bg-surface-hover hover:text-foreground"
      >
        {initialsOf(user.display_name)}
      </button>

      {open && (
        <div
          role="menu"
          className="animate-scale-in absolute right-0 top-10 z-50 w-56 overflow-hidden rounded-sb border border-border-strong bg-surface shadow-xl shadow-black/40"
        >
          <div className="border-b border-border px-3 py-2.5">
            <p className="truncate text-sm font-medium">{user.display_name}</p>
            <p className="truncate text-xs text-subtle">{user.email}</p>
          </div>
          <Link
            href="/settings"
            role="menuitem"
            onClick={() => setOpen(false)}
            className="flex items-center gap-2.5 px-3 py-2.5 text-sm text-muted hover:bg-surface-hover hover:text-foreground"
          >
            <Settings className="size-4" />
            Settings
          </Link>
          <button
            type="button"
            role="menuitem"
            onClick={() => void logout()}
            className="flex w-full items-center gap-2.5 px-3 py-2.5 text-sm text-muted hover:bg-surface-hover hover:text-foreground"
          >
            <LogOut className="size-4" />
            Sign out
          </button>
        </div>
      )}
    </div>
  );
}

export function Topbar({ onOpenPalette }: { onOpenPalette: () => void }) {
  return (
    <header className="flex h-14 shrink-0 items-center gap-4 border-b border-border px-4 md:px-6">
      <button
        type="button"
        onClick={onOpenPalette}
        className="flex h-9 max-w-md flex-1 items-center gap-2.5 rounded-sb border border-border bg-surface/50 px-3 text-sm text-subtle transition-colors hover:border-border-strong hover:bg-surface"
      >
        <Search className="size-4" />
        <span>Search everything you own…</span>
        <kbd className="ml-auto hidden rounded border border-border bg-background px-1.5 py-0.5 font-mono text-[10px] text-subtle sm:inline">
          ⌘K
        </kbd>
      </button>

      <div className="ml-auto flex items-center gap-4">
        <StatusDot />
        <UserMenu />
      </div>
    </header>
  );
}

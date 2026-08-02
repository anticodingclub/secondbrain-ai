"use client";

import { Search } from "lucide-react";

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

      <div className="ml-auto">
        <StatusDot />
      </div>
    </header>
  );
}

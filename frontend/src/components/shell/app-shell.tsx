"use client";

import type { ReactNode } from "react";

import { CommandPalette } from "@/components/shell/command-palette";
import { Sidebar } from "@/components/shell/sidebar";
import { Topbar } from "@/components/shell/topbar";
import { useCommandPalette } from "@/hooks/use-command-palette";

export function AppShell({ children }: { children: ReactNode }) {
  const { open, setOpen } = useCommandPalette();

  return (
    <div className="flex h-dvh overflow-hidden">
      <Sidebar />
      <div className="flex min-w-0 flex-1 flex-col">
        <Topbar onOpenPalette={() => setOpen(true)} />
        <main className="flex-1 overflow-y-auto">{children}</main>
      </div>
      <CommandPalette open={open} onOpenChange={setOpen} />
    </div>
  );
}

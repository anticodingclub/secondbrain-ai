"use client";

import { Command } from "cmdk";
import { Search } from "lucide-react";
import { useRouter } from "next/navigation";

import { NAV_ITEMS } from "@/lib/navigation";

interface CommandPaletteProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function CommandPalette({ open, onOpenChange }: CommandPaletteProps) {
  const router = useRouter();

  return (
    <Command.Dialog
      open={open}
      onOpenChange={onOpenChange}
      label="Command palette"
      className="fixed inset-0 z-50"
    >
      <button
        type="button"
        aria-label="Close command palette"
        className="absolute inset-0 h-full w-full cursor-default bg-black/60 backdrop-blur-sm"
        onClick={() => onOpenChange(false)}
      />
      <div className="animate-scale-in relative mx-auto mt-[15vh] w-[92vw] max-w-lg overflow-hidden rounded-sb border border-border-strong bg-surface shadow-2xl shadow-black/50">
        <div className="flex items-center gap-3 border-b border-border px-4">
          <Search className="size-4 shrink-0 text-subtle" />
          <Command.Input
            placeholder="Search or jump to…"
            className="h-12 w-full bg-transparent text-sm outline-none placeholder:text-subtle"
          />
        </div>

        <Command.List className="max-h-80 overflow-y-auto p-2">
          <Command.Empty className="px-3 py-8 text-center text-sm text-subtle">
            No results.
          </Command.Empty>

          <Command.Group
            heading="Navigate"
            className="[&_[cmdk-group-heading]]:px-3 [&_[cmdk-group-heading]]:py-2 [&_[cmdk-group-heading]]:text-xs [&_[cmdk-group-heading]]:font-medium [&_[cmdk-group-heading]]:text-subtle"
          >
            {NAV_ITEMS.map(({ label, icon: Icon, href }) => (
              <Command.Item
                key={label}
                value={label}
                disabled={!href}
                onSelect={() => {
                  if (!href) return;
                  router.push(href);
                  onOpenChange(false);
                }}
                className="flex cursor-pointer items-center gap-3 rounded-lg px-3 py-2.5 text-sm text-muted data-[disabled=true]:cursor-not-allowed data-[disabled=true]:opacity-40 data-[selected=true]:bg-surface-hover data-[selected=true]:text-foreground"
              >
                <Icon className="size-4" />
                {label}
                {!href && (
                  <span className="ml-auto text-[10px] text-subtle">soon</span>
                )}
              </Command.Item>
            ))}
          </Command.Group>
        </Command.List>
      </div>
    </Command.Dialog>
  );
}

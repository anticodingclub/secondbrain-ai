"use client";

import { AlertCircle, Check, Copy, X } from "lucide-react";

import type { UploadItem, UploadState } from "@/hooks/use-uploads";
import { formatBytes } from "@/lib/format";
import { cn } from "@/lib/utils";

const TERMINAL: Record<string, { label: string; tone: string }> = {
  done: { label: "Uploaded", tone: "text-success" },
  duplicate: { label: "Already in your library", tone: "text-muted" },
  failed: { label: "Failed", tone: "text-danger" },
  cancelled: { label: "Cancelled", tone: "text-subtle" },
};

function StateIcon({ state }: { state: UploadState }) {
  switch (state) {
    case "done":
      return <Check className="size-4 text-success" />;
    case "duplicate":
      return <Copy className="size-4 text-muted" />;
    case "failed":
      return <AlertCircle className="size-4 text-danger" />;
    default:
      return null;
  }
}

interface UploadQueueProps {
  items: UploadItem[];
  onCancel: (id: string) => void;
  onClearFinished: () => void;
}

export function UploadQueue({ items, onCancel, onClearFinished }: UploadQueueProps) {
  if (items.length === 0) return null;

  const finished = items.filter((item) => item.state in TERMINAL).length;

  return (
    <section className="animate-fade-up mt-6" aria-label="Upload queue">
      <div className="mb-2 flex items-center justify-between">
        <h2 className="text-sm font-medium text-muted">
          Uploads
          <span className="ml-2 text-xs text-subtle">
            {finished} of {items.length} finished
          </span>
        </h2>
        {finished > 0 && (
          <button
            type="button"
            onClick={onClearFinished}
            className="text-xs text-subtle transition-colors hover:text-foreground"
          >
            Clear finished
          </button>
        )}
      </div>

      <ul className="space-y-1.5">
        {items.map((item) => {
          const terminal = TERMINAL[item.state];
          const isActive = item.state === "uploading" || item.state === "queued";

          return (
            <li
              key={item.id}
              className="rounded-sb border border-border bg-surface/50 px-3.5 py-2.5"
            >
              <div className="flex items-center gap-3">
                <StateIcon state={item.state} />
                <span className="min-w-0 flex-1 truncate text-sm" title={item.filename}>
                  {item.filename}
                </span>
                <span className="shrink-0 text-xs text-subtle">
                  {formatBytes(item.sizeBytes)}
                </span>

                {isActive ? (
                  <>
                    <span className="w-9 shrink-0 text-right font-mono text-xs text-muted">
                      {item.state === "queued" ? "—" : `${item.progress}%`}
                    </span>
                    <button
                      type="button"
                      onClick={() => onCancel(item.id)}
                      aria-label={`Cancel upload of ${item.filename}`}
                      className="shrink-0 text-subtle transition-colors hover:text-danger"
                    >
                      <X className="size-4" />
                    </button>
                  </>
                ) : (
                  <span className={cn("shrink-0 text-xs", terminal?.tone)}>
                    {terminal?.label}
                  </span>
                )}
              </div>

              {isActive && (
                <div
                  className="mt-2 h-1 overflow-hidden rounded-full bg-border"
                  role="progressbar"
                  aria-valuenow={item.progress}
                  aria-valuemin={0}
                  aria-valuemax={100}
                  aria-label={`Uploading ${item.filename}`}
                >
                  <div
                    className="h-full rounded-full bg-accent transition-[width] duration-200"
                    style={{ width: `${item.progress}%` }}
                  />
                </div>
              )}

              {item.error && (
                <p role="alert" className="mt-1.5 text-xs text-danger">
                  {item.error}
                </p>
              )}
            </li>
          );
        })}
      </ul>
    </section>
  );
}

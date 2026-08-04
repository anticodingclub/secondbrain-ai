"use client";

import { Download, FileText, Loader2, Trash2 } from "lucide-react";
import { useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { useDeleteDocument } from "@/hooks/use-documents";
import { documentContentUrl } from "@/lib/api/documents";
import type { DocumentRecord, DocumentStatus } from "@/lib/api/types";
import { formatBytes, formatRelativeTime } from "@/lib/format";

const STATUS_VARIANT: Record<
  DocumentStatus,
  "neutral" | "accent" | "success" | "warning" | "danger"
> = {
  pending: "neutral",
  parsing: "warning",
  chunking: "warning",
  embedding: "warning",
  indexed: "success",
  failed: "danger",
};

/** Phase 3 stores documents; parsing and indexing arrive in Phases 4–5. */
const STATUS_LABEL: Record<DocumentStatus, string> = {
  pending: "awaiting parsing",
  parsing: "parsing",
  chunking: "chunking",
  embedding: "embedding",
  indexed: "indexed",
  failed: "failed",
};

function DocumentRow({ document }: { document: DocumentRecord }) {
  const remove = useDeleteDocument();
  const [confirming, setConfirming] = useState(false);

  return (
    <li className="group flex items-center gap-3 px-4 py-3 transition-colors hover:bg-surface-hover">
      <span className="grid size-9 shrink-0 place-items-center rounded-sb bg-background-subtle text-subtle">
        <FileText className="size-4" />
      </span>

      <div className="min-w-0 flex-1">
        <p className="truncate text-sm font-medium" title={document.original_filename}>
          {document.title || document.original_filename}
        </p>
        <p className="mt-0.5 truncate text-xs text-subtle">
          {document.extension.toUpperCase()} · {formatBytes(document.size_bytes)} ·{" "}
          {formatRelativeTime(document.created_at)}
        </p>
      </div>

      <Badge variant={STATUS_VARIANT[document.status]}>
        {STATUS_LABEL[document.status]}
      </Badge>

      <div className="flex shrink-0 items-center gap-1">
        <a
          href={documentContentUrl(document.id)}
          target="_blank"
          rel="noreferrer"
          aria-label={`Open ${document.title}`}
          className="rounded p-1.5 text-subtle transition-colors hover:bg-surface hover:text-foreground"
        >
          <Download className="size-4" />
        </a>

        {confirming ? (
          <span className="flex items-center gap-1">
            <button
              type="button"
              onClick={() => remove.mutate(document.id)}
              disabled={remove.isPending}
              className="rounded px-2 py-1 text-xs text-danger transition-colors hover:bg-danger/10"
            >
              {remove.isPending ? "Deleting…" : "Confirm"}
            </button>
            <button
              type="button"
              onClick={() => setConfirming(false)}
              className="rounded px-2 py-1 text-xs text-subtle transition-colors hover:text-foreground"
            >
              Cancel
            </button>
          </span>
        ) : (
          <button
            type="button"
            onClick={() => setConfirming(true)}
            aria-label={`Delete ${document.title}`}
            className="rounded p-1.5 text-subtle transition-colors hover:bg-danger/10 hover:text-danger"
          >
            <Trash2 className="size-4" />
          </button>
        )}
      </div>
    </li>
  );
}

interface DocumentListProps {
  documents: DocumentRecord[];
  isLoading: boolean;
  isFetching: boolean;
  emptyMessage: string;
}

export function DocumentList({
  documents,
  isLoading,
  isFetching,
  emptyMessage,
}: DocumentListProps) {
  if (isLoading) {
    return (
      <ul className="divide-y divide-border">
        {[0, 1, 2].map((index) => (
          <li key={index} className="flex items-center gap-3 px-4 py-3">
            <Skeleton className="size-9 rounded-sb" />
            <div className="flex-1 space-y-2">
              <Skeleton className="h-3.5 w-48" />
              <Skeleton className="h-3 w-32" />
            </div>
          </li>
        ))}
      </ul>
    );
  }

  if (documents.length === 0) {
    return <p className="px-4 py-10 text-center text-sm text-muted">{emptyMessage}</p>;
  }

  return (
    <div className="relative">
      {/* Refetches keep the current rows visible; this only marks them stale. */}
      {isFetching && (
        <Loader2
          className="absolute right-3 top-3 size-3.5 animate-spin text-subtle"
          aria-label="Refreshing"
        />
      )}
      <ul className="divide-y divide-border">
        {documents.map((document) => (
          <DocumentRow key={document.id} document={document} />
        ))}
      </ul>
    </div>
  );
}

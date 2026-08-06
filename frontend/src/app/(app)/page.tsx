"use client";

import {
  AlertCircle,
  FileText,
  HardDrive,
  Layers,
  MessagesSquare,
  Search,
  Upload,
} from "lucide-react";
import Link from "next/link";
import type { ReactNode } from "react";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { useDashboard } from "@/hooks/use-dashboard";
import { useSystemInfo } from "@/hooks/use-system-info";
import { formatBytes, formatRelativeTime } from "@/lib/format";
import type { DocumentStatus } from "@/lib/api/types";
import { cn } from "@/lib/utils";

const STATUS_VARIANT: Record<DocumentStatus, "neutral" | "success" | "warning" | "danger"> =
  {
    pending: "neutral",
    parsing: "warning",
    chunking: "warning",
    embedding: "warning",
    indexed: "success",
    failed: "danger",
  };

function Stat({
  icon: Icon,
  label,
  value,
  hint,
}: {
  icon: typeof FileText;
  label: string;
  value: ReactNode;
  hint?: string;
}) {
  return (
    <Card className="animate-fade-up">
      <CardContent className="p-4">
        <div className="flex items-center gap-2 text-xs text-subtle">
          <Icon className="size-3.5" />
          {label}
        </div>
        <p className="mt-2 text-2xl font-semibold tracking-tight">{value}</p>
        {hint && <p className="mt-0.5 text-xs text-subtle">{hint}</p>}
      </CardContent>
    </Card>
  );
}

function EmptyLibrary() {
  return (
    <Card className="animate-fade-up">
      <CardContent className="py-14 text-center">
        <span className="mx-auto grid size-11 place-items-center rounded-full bg-surface text-muted">
          <Upload className="size-5" />
        </span>
        <h2 className="mt-4 text-base font-medium">Nothing indexed yet</h2>
        <p className="mx-auto mt-1.5 max-w-sm text-sm text-muted">
          Upload a document and SecondBrain will extract its text, index it, and
          make it answerable.
        </p>
        <Link
          href="/documents"
          className="mt-5 inline-flex items-center gap-2 rounded-sb bg-accent px-3.5 py-2 text-sm font-medium text-accent-contrast transition-opacity hover:opacity-90"
        >
          <Upload className="size-4" />
          Add your first document
        </Link>
      </CardContent>
    </Card>
  );
}

export default function DashboardPage() {
  const { data, isLoading } = useDashboard();
  const system = useSystemInfo();

  if (isLoading) {
    return (
      <div className="mx-auto max-w-5xl px-4 py-10 md:px-8">
        <Skeleton className="h-8 w-48" />
        <div className="mt-8 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {[0, 1, 2, 3].map((index) => (
            <Skeleton key={index} className="h-24 rounded-sb" />
          ))}
        </div>
      </div>
    );
  }

  const stats = data;
  const isEmpty = !stats || stats.document_count === 0;
  const progress = Math.round((stats?.indexing_progress ?? 1) * 100);

  return (
    <div className="mx-auto max-w-5xl px-4 py-10 md:px-8">
      <header className="animate-fade-up">
        <h1 className="text-2xl font-semibold tracking-tight">Your second brain</h1>
        <p className="mt-1.5 text-sm text-muted">
          {isEmpty
            ? "Ask questions in plain language and get answers from everything you own."
            : `${stats.indexed_count} of ${stats.document_count} documents ready to search.`}
        </p>
      </header>

      {isEmpty ? (
        <div className="mt-8">
          <EmptyLibrary />
        </div>
      ) : (
        <>
          <section className="mt-8 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <Stat
              icon={FileText}
              label="Documents"
              value={stats.document_count}
              hint={`${formatBytes(stats.total_bytes)} stored`}
            />
            <Stat
              icon={Layers}
              label="Indexed chunks"
              value={stats.chunk_count.toLocaleString()}
              hint={`${stats.vector_count.toLocaleString()} vectors`}
            />
            <Stat
              icon={Search}
              label="Searches"
              value={stats.search_count}
              hint={
                stats.search_count > 0
                  ? `${stats.median_search_ms} ms typical`
                  : "none yet"
              }
            />
            <Stat
              icon={MessagesSquare}
              label="Conversations"
              value={stats.conversation_count}
              hint={`${stats.message_count} messages`}
            />
          </section>

          {(stats.pending_count > 0 || stats.failed_count > 0) && (
            <section className="animate-fade-up mt-3">
              <Card>
                <CardContent className="flex flex-wrap items-center gap-4 p-4">
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center justify-between text-xs">
                      <span className="text-muted">
                        {stats.pending_count > 0
                          ? `Indexing ${stats.pending_count} document${stats.pending_count === 1 ? "" : "s"}…`
                          : "Indexing complete"}
                      </span>
                      <span className="font-mono text-subtle">{progress}%</span>
                    </div>
                    <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-border">
                      <div
                        className="h-full rounded-full bg-accent transition-[width] duration-500"
                        style={{ width: `${progress}%` }}
                      />
                    </div>
                  </div>
                  {stats.failed_count > 0 && (
                    <Link
                      href="/documents"
                      className="flex items-center gap-1.5 text-xs text-danger hover:underline"
                    >
                      <AlertCircle className="size-3.5" />
                      {stats.failed_count} failed
                    </Link>
                  )}
                </CardContent>
              </Card>
            </section>
          )}

          <div className="mt-8 grid gap-6 lg:grid-cols-2">
            <section>
              <h2 className="text-sm font-medium text-muted">Recent uploads</h2>
              <Card className="animate-fade-up mt-3">
                <CardContent className="divide-y divide-border p-0">
                  {stats.recent_documents.map((document) => (
                    <div
                      key={document.id}
                      className="flex items-center gap-3 px-4 py-2.5"
                    >
                      <FileText className="size-3.5 shrink-0 text-subtle" />
                      <span className="min-w-0 flex-1 truncate text-sm">
                        {document.title}
                      </span>
                      <span className="shrink-0 text-xs text-subtle">
                        {formatRelativeTime(document.created_at)}
                      </span>
                      <Badge variant={STATUS_VARIANT[document.status]}>
                        {document.status}
                      </Badge>
                    </div>
                  ))}
                </CardContent>
              </Card>
            </section>

            <section>
              <h2 className="text-sm font-medium text-muted">Recent searches</h2>
              <Card className="animate-fade-up mt-3">
                <CardContent className="divide-y divide-border p-0">
                  {stats.recent_searches.length === 0 ? (
                    <p className="px-4 py-8 text-center text-sm text-muted">
                      No searches yet.{" "}
                      <Link href="/search" className="text-accent hover:underline">
                        Try one
                      </Link>
                      .
                    </p>
                  ) : (
                    stats.recent_searches.map((search, index) => (
                      <div
                        key={`${search.query}-${index}`}
                        className="flex items-center gap-3 px-4 py-2.5"
                      >
                        <Search className="size-3.5 shrink-0 text-subtle" />
                        <span className="min-w-0 flex-1 truncate text-sm">
                          {search.query}
                        </span>
                        <span
                          className={cn(
                            "shrink-0 text-xs",
                            search.hit_count === 0 ? "text-warning" : "text-subtle",
                          )}
                        >
                          {search.hit_count} hit{search.hit_count === 1 ? "" : "s"}
                        </span>
                        <span className="shrink-0 font-mono text-xs text-subtle">
                          {search.took_ms}ms
                        </span>
                      </div>
                    ))
                  )}
                </CardContent>
              </Card>
            </section>
          </div>

          {stats.by_extension.length > 0 && (
            <section className="mt-8">
              <h2 className="text-sm font-medium text-muted">By file type</h2>
              <div className="mt-3 flex flex-wrap gap-2">
                {stats.by_extension.map((entry) => (
                  <span
                    key={entry.label}
                    className="rounded-full border border-border px-3 py-1 text-xs text-muted"
                  >
                    {entry.label.toUpperCase()}
                    <span className="ml-1.5 text-subtle">{entry.count}</span>
                  </span>
                ))}
              </div>
            </section>
          )}
        </>
      )}

      <section className="mt-10">
        <h2 className="text-sm font-medium text-muted">This instance</h2>
        <Card className="animate-fade-up mt-3">
          <CardContent className="grid gap-x-8 gap-y-2 p-4 text-sm sm:grid-cols-2">
            {[
              ["Embedding model", system.data?.embedding.model],
              ["Vector store", system.data && `${system.data.vector_store.backend} (${system.data.vector_store.mode})`],
              ["Language model", system.data && `${system.data.llm_model} via ${system.data.llm_provider}`],
              ["Storage", system.data?.storage_backend],
            ].map(([label, value]) => (
              <div key={String(label)} className="flex items-center justify-between gap-4">
                <span className="text-muted">{label}</span>
                <span className="truncate font-mono text-xs">{value ?? "—"}</span>
              </div>
            ))}
          </CardContent>
        </Card>
        <p className="mt-3 flex items-center gap-1.5 text-xs text-subtle">
          <HardDrive className="size-3" />
          Everything is stored on this machine.
        </p>
      </section>
    </div>
  );
}

"use client";

import { Search } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { DocumentList } from "@/components/documents/document-list";
import { Dropzone } from "@/components/documents/dropzone";
import { UploadQueue } from "@/components/documents/upload-queue";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { useDocuments, useStorageUsage } from "@/hooks/use-documents";
import { useUploads } from "@/hooks/use-uploads";
import { formatBytes } from "@/lib/format";

const PAGE_SIZE = 25;

export default function DocumentsPage() {
  const [search, setSearch] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const [offset, setOffset] = useState(0);

  const { items, enqueue, cancel, clearFinished, activeCount } = useUploads();
  const usage = useStorageUsage();

  // Debounced so typing does not fire a request per keystroke.
  useEffect(() => {
    const timer = setTimeout(() => {
      setDebouncedSearch(search);
      setOffset(0); // a new query invalidates the current page number
    }, 250);
    return () => clearTimeout(timer);
  }, [search]);

  const filters = useMemo(
    () => ({ search: debouncedSearch || undefined, limit: PAGE_SIZE, offset }),
    [debouncedSearch, offset],
  );

  const documents = useDocuments(filters);
  const total = documents.data?.total ?? 0;
  const shown = (documents.data?.items ?? []).length;
  const hasMore = offset + shown < total;

  return (
    <div className="mx-auto max-w-4xl px-4 py-10 md:px-8">
      <header className="animate-fade-up flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Documents</h1>
          <p className="mt-1.5 text-sm text-muted">
            Everything you have given SecondBrain to remember.
          </p>
        </div>
        {usage.data && (
          <p className="text-sm text-subtle">
            <span className="font-medium text-foreground">{usage.data.document_count}</span>{" "}
            {usage.data.document_count === 1 ? "document" : "documents"} ·{" "}
            {formatBytes(usage.data.total_bytes)}
          </p>
        )}
      </header>

      <div className="animate-fade-up mt-6">
        <Dropzone onFiles={(files) => void enqueue(files)} />
      </div>

      <UploadQueue items={items} onCancel={cancel} onClearFinished={clearFinished} />

      <section className="mt-8">
        <div className="mb-3 flex items-center gap-3">
          <div className="relative flex-1">
            <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-subtle" />
            <Input
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Filter by name…"
              aria-label="Filter documents by name"
              className="pl-9"
            />
          </div>
          {total > 0 && (
            <span className="shrink-0 text-xs text-subtle">
              {offset + 1}–{offset + shown} of {total}
            </span>
          )}
        </div>

        <Card className="animate-fade-up overflow-hidden">
          <CardContent className="p-0">
            <DocumentList
              documents={documents.data?.items ?? []}
              isLoading={documents.isLoading}
              isFetching={documents.isFetching && !documents.isLoading}
              emptyMessage={
                debouncedSearch
                  ? `Nothing matches “${debouncedSearch}”.`
                  : activeCount > 0
                    ? "Uploading…"
                    : "No documents yet. Drop a file above to get started."
              }
            />
          </CardContent>
        </Card>

        {(offset > 0 || hasMore) && (
          <div className="mt-4 flex justify-between">
            <Button
              onClick={() => setOffset((value) => Math.max(0, value - PAGE_SIZE))}
              disabled={offset === 0}
            >
              Previous
            </Button>
            <Button onClick={() => setOffset((value) => value + PAGE_SIZE)} disabled={!hasMore}>
              Next
            </Button>
          </div>
        )}
      </section>
    </div>
  );
}

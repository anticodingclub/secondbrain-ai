"use client";

import { AlertCircle, FolderGit2, RefreshCw, Trash2 } from "lucide-react";
import { type FormEvent, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import {
  useDeleteRepository,
  useImportRepository,
  useRepositories,
  useSyncRepository,
} from "@/hooks/use-repositories";
import { ApiError } from "@/lib/api/client";
import type { RepositoryRecord, RepositoryStatus } from "@/lib/api/types";
import { formatRelativeTime } from "@/lib/format";

const STATUS_VARIANT: Record<
  RepositoryStatus,
  "neutral" | "accent" | "success" | "warning" | "danger"
> = {
  pending: "neutral",
  cloning: "warning",
  importing: "warning",
  ready: "success",
  failed: "danger",
};

const STATUS_LABEL: Record<RepositoryStatus, string> = {
  pending: "queued",
  cloning: "cloning…",
  importing: "indexing…",
  ready: "ready",
  failed: "failed",
};

function RepositoryRow({ repository }: { repository: RepositoryRecord }) {
  const sync = useSyncRepository();
  const remove = useDeleteRepository();
  const [confirming, setConfirming] = useState(false);

  const busy = ["pending", "cloning", "importing"].includes(repository.status);
  const skipReasons = repository.repo_metadata?.skip_reasons as
    | Record<string, number>
    | undefined;

  return (
    <li className="px-4 py-3">
      <div className="flex items-center gap-3">
        <FolderGit2 className="size-4 shrink-0 text-subtle" />

        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-medium">
            {repository.owner_name}/{repository.repo_name}
          </p>
          <p className="mt-0.5 truncate text-xs text-subtle">
            {repository.status === "ready"
              ? `${repository.file_count} files indexed` +
                (repository.skipped_count > 0
                  ? ` · ${repository.skipped_count} skipped`
                  : "") +
                (repository.last_synced_at
                  ? ` · ${formatRelativeTime(repository.last_synced_at)}`
                  : "")
              : repository.clone_url}
            {repository.commit_sha && repository.status === "ready" && (
              <span className="ml-1.5 font-mono">
                {repository.commit_sha.slice(0, 7)}
              </span>
            )}
          </p>
        </div>

        <Badge variant={STATUS_VARIANT[repository.status]}>
          {STATUS_LABEL[repository.status]}
        </Badge>

        <div className="flex shrink-0 items-center gap-1">
          <button
            type="button"
            onClick={() => sync.mutate(repository.id)}
            disabled={busy || sync.isPending}
            aria-label={`Re-sync ${repository.repo_name}`}
            className="rounded p-1.5 text-subtle transition-colors hover:bg-surface hover:text-foreground disabled:opacity-40"
          >
            <RefreshCw className={busy ? "size-4 animate-spin" : "size-4"} />
          </button>

          {confirming ? (
            <span className="flex items-center gap-1">
              <button
                type="button"
                onClick={() => remove.mutate(repository.id)}
                className="rounded px-2 py-1 text-xs text-danger transition-colors hover:bg-danger/10"
              >
                Confirm
              </button>
              <button
                type="button"
                onClick={() => setConfirming(false)}
                className="rounded px-2 py-1 text-xs text-subtle hover:text-foreground"
              >
                Cancel
              </button>
            </span>
          ) : (
            <button
              type="button"
              onClick={() => setConfirming(true)}
              aria-label={`Remove ${repository.repo_name}`}
              className="rounded p-1.5 text-subtle transition-colors hover:bg-danger/10 hover:text-danger"
            >
              <Trash2 className="size-4" />
            </button>
          )}
        </div>
      </div>

      {repository.error_message && (
        <p
          role="alert"
          className="mt-2 flex items-start gap-1.5 pl-7 text-xs text-danger"
        >
          <AlertCircle className="mt-0.5 size-3 shrink-0" />
          {repository.error_message}
        </p>
      )}

      {/* "Why is my file missing?" deserves an answer. */}
      {repository.status === "ready" && skipReasons && (
        <p className="mt-1.5 pl-7 text-xs text-subtle">
          Skipped:{" "}
          {Object.entries(skipReasons)
            .map(([reason, count]) => `${count} ${reason}`)
            .join(", ")}
        </p>
      )}
    </li>
  );
}

export default function RepositoriesPage() {
  const [reference, setReference] = useState("");
  const repositories = useRepositories();
  const importRepo = useImportRepository();

  function onSubmit(event: FormEvent) {
    event.preventDefault();
    const trimmed = reference.trim();
    if (!trimmed) return;
    importRepo.mutate(trimmed, { onSuccess: () => setReference("") });
  }

  return (
    <div className="mx-auto max-w-3xl px-4 py-10 md:px-8">
      <header className="animate-fade-up">
        <h1 className="text-2xl font-semibold tracking-tight">Repositories</h1>
        <p className="mt-1.5 text-sm text-muted">
          Import a public GitHub repository and ask questions about its code.
        </p>
      </header>

      <form onSubmit={onSubmit} className="animate-fade-up mt-6">
        <div className="flex gap-2">
          <Input
            value={reference}
            onChange={(event) => setReference(event.target.value)}
            placeholder="owner/name or https://github.com/owner/name"
            aria-label="Repository to import"
            className="h-11"
          />
          <Button
            type="submit"
            variant="primary"
            disabled={!reference.trim() || importRepo.isPending}
          >
            {importRepo.isPending ? "Importing…" : "Import"}
          </Button>
        </div>
        {importRepo.isError && (
          <p
            role="alert"
            className="mt-2 rounded-sb border border-danger/40 bg-danger/10 px-3 py-2 text-xs text-danger"
          >
            {importRepo.error instanceof ApiError
              ? importRepo.error.message
              : "The import failed."}
          </p>
        )}
        <p className="mt-2 text-xs text-subtle">
          Only public repositories. Vendored trees, lockfiles and binaries are
          skipped so they do not drown out real code.
        </p>
      </form>

      <section className="mt-8">
        {repositories.isLoading ? (
          <Card>
            <CardContent className="space-y-3 p-4">
              <Skeleton className="h-4 w-48" />
              <Skeleton className="h-4 w-64" />
            </CardContent>
          </Card>
        ) : repositories.data && repositories.data.length > 0 ? (
          <Card className="animate-fade-up overflow-hidden">
            <CardContent className="p-0">
              <ul className="divide-y divide-border">
                {repositories.data.map((repository) => (
                  <RepositoryRow key={repository.id} repository={repository} />
                ))}
              </ul>
            </CardContent>
          </Card>
        ) : (
          <Card className="animate-fade-up">
            <CardContent className="py-12 text-center">
              <span className="mx-auto grid size-11 place-items-center rounded-full bg-surface text-muted">
                <FolderGit2 className="size-5" />
              </span>
              <p className="mt-4 text-sm text-muted">No repositories imported yet.</p>
              <p className="mt-1 text-xs text-subtle">
                Try <code className="text-foreground">tiangolo/fastapi</code>.
              </p>
            </CardContent>
          </Card>
        )}
      </section>
    </div>
  );
}

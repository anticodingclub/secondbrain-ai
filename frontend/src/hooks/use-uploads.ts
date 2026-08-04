"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useRef, useState } from "react";

import { documentKeys } from "@/hooks/use-documents";
import { ApiError } from "@/lib/api/client";
import { uploadDocument } from "@/lib/api/documents";

export type UploadState =
  | "queued"
  | "uploading"
  | "done"
  | "duplicate"
  | "failed"
  | "cancelled";

export interface UploadItem {
  id: string;
  filename: string;
  sizeBytes: number;
  state: UploadState;
  progress: number;
  error?: string;
}

/**
 * How many files transfer at once.
 *
 * Browsers cap concurrent connections per origin at around six, so firing
 * fifty uploads at once does not make them faster — it starves every other
 * request, including the token refresh, behind a queue of large bodies.
 */
const MAX_CONCURRENT = 3;

export function useUploads() {
  const [items, setItems] = useState<UploadItem[]>([]);
  const controllers = useRef(new Map<string, AbortController>());
  const queryClient = useQueryClient();

  const patch = useCallback((id: string, changes: Partial<UploadItem>) => {
    setItems((current) =>
      current.map((item) => (item.id === id ? { ...item, ...changes } : item)),
    );
  }, []);

  const runOne = useCallback(
    async (id: string, file: File) => {
      const controller = new AbortController();
      controllers.current.set(id, controller);
      patch(id, { state: "uploading", progress: 0 });

      try {
        const result = await uploadDocument({
          file,
          signal: controller.signal,
          onProgress: (progress) => patch(id, { progress }),
        });
        patch(id, {
          state: result.was_duplicate ? "duplicate" : "done",
          progress: 100,
        });
      } catch (cause) {
        if (cause instanceof DOMException && cause.name === "AbortError") {
          patch(id, { state: "cancelled" });
        } else {
          patch(id, {
            state: "failed",
            error: cause instanceof ApiError ? cause.message : "The upload failed.",
          });
        }
      } finally {
        controllers.current.delete(id);
      }
    },
    [patch],
  );

  const enqueue = useCallback(
    async (files: File[]) => {
      if (files.length === 0) return;

      const queued = files.map((file) => ({
        id: crypto.randomUUID(),
        file,
      }));

      setItems((current) => [
        ...queued.map(({ id, file }) => ({
          id,
          filename: file.name,
          sizeBytes: file.size,
          state: "queued" as const,
          progress: 0,
        })),
        ...current,
      ]);

      // A hand-rolled pool rather than Promise.all: the point is to keep at
      // most MAX_CONCURRENT transfers in flight, not to start them all.
      const pending = [...queued];
      const workers = Array.from(
        { length: Math.min(MAX_CONCURRENT, pending.length) },
        async () => {
          while (pending.length > 0) {
            const next = pending.shift();
            if (next) await runOne(next.id, next.file);
          }
        },
      );

      await Promise.all(workers);

      // One invalidation for the whole batch — invalidating per file would
      // refetch the list N times for a single visible change.
      await queryClient.invalidateQueries({ queryKey: documentKeys.all });
    },
    [runOne, queryClient],
  );

  const cancel = useCallback((id: string) => {
    controllers.current.get(id)?.abort();
  }, []);

  const clearFinished = useCallback(() => {
    setItems((current) =>
      current.filter((item) => item.state === "uploading" || item.state === "queued"),
    );
  }, []);

  const activeCount = items.filter(
    (item) => item.state === "uploading" || item.state === "queued",
  ).length;

  return { items, enqueue, cancel, clearFinished, activeCount };
}

import { ApiError, api, refreshAccessToken } from "@/lib/api/client";
import { getAccessToken } from "@/lib/api/token-store";
import type {
  ApiErrorBody,
  DocumentFilters,
  DocumentRecord,
  Page,
  StorageUsage,
  UploadResponse,
} from "@/lib/api/types";

const BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export function listDocuments(
  filters: DocumentFilters = {},
): Promise<Page<DocumentRecord>> {
  const params: Record<string, string | number | undefined> = {
    limit: filters.limit,
    offset: filters.offset,
    status: filters.status,
    search: filters.search || undefined,
    collection_id: filters.collectionId,
  };

  // `extension` is repeatable server-side, which a flat params object cannot
  // express, so it is appended by hand.
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== "") {
      query.set(key, String(value));
    }
  }
  for (const extension of filters.extensions ?? []) {
    query.append("extension", extension);
  }

  const suffix = query.toString();
  return api.get<Page<DocumentRecord>>(`/documents${suffix ? `?${suffix}` : ""}`);
}

export function getDocument(id: string): Promise<DocumentRecord> {
  return api.get<DocumentRecord>(`/documents/${id}`);
}

export function deleteDocument(id: string): Promise<void> {
  return api.delete<void>(`/documents/${id}`);
}

export function getStorageUsage(): Promise<StorageUsage> {
  return api.get<StorageUsage>("/documents/usage");
}

export function documentContentUrl(id: string): string {
  return `${BASE_URL}/api/v1/documents/${id}/content`;
}

export interface UploadOptions {
  file: File;
  collectionId?: string;
  onProgress?: (percent: number) => void;
  signal?: AbortSignal;
}

/**
 * Upload one file, reporting progress.
 *
 * This is the one place that uses XMLHttpRequest rather than fetch: fetch
 * still cannot report *upload* progress in any browser, and a large file with
 * no visible progress reads as a frozen page. The rest of the client stays on
 * fetch.
 */
export async function uploadDocument({
  file,
  collectionId,
  onProgress,
  signal,
}: UploadOptions): Promise<UploadResponse> {
  // Refresh up front if needed. XHR cannot replay itself on a 401 the way
  // apiFetch does, and re-sending a large body would double the transfer.
  if (!getAccessToken()) await refreshAccessToken();

  return new Promise<UploadResponse>((resolve, reject) => {
    const request = new XMLHttpRequest();
    const form = new FormData();
    form.append("file", file);
    if (collectionId) form.append("collection_id", collectionId);

    request.open("POST", `${BASE_URL}/api/v1/documents/upload`);
    request.withCredentials = true;

    const token = getAccessToken();
    if (token) request.setRequestHeader("Authorization", `Bearer ${token}`);

    request.upload.addEventListener("progress", (event) => {
      if (event.lengthComputable) {
        onProgress?.(Math.round((event.loaded / event.total) * 100));
      }
    });

    request.addEventListener("load", () => {
      let payload: unknown = null;
      try {
        payload = JSON.parse(request.responseText) as unknown;
      } catch {
        // Falls through to the generic error below.
      }

      if (request.status >= 200 && request.status < 300) {
        onProgress?.(100);
        resolve(payload as UploadResponse);
        return;
      }

      reject(
        new ApiError(
          request.status,
          (payload as ApiErrorBody) ?? {
            error: "upload_failed",
            message: "The upload failed.",
          },
        ),
      );
    });

    request.addEventListener("error", () => {
      reject(
        new ApiError(0, {
          error: "network_error",
          message: "The connection dropped during upload.",
        }),
      );
    });

    request.addEventListener("abort", () => {
      reject(new DOMException("Upload cancelled", "AbortError"));
    });

    signal?.addEventListener("abort", () => request.abort(), { once: true });

    request.send(form);
  });
}

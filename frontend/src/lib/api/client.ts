import type { ApiErrorBody } from "./types";

const BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const API_PREFIX = "/api/v1";

/**
 * A failed API call, carrying the backend's structured error envelope.
 *
 * `requestId` is the thread back to the server-side logs, so surfacing it in
 * error UI turns "it broke" into something diagnosable.
 */
export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly details?: Record<string, unknown>;
  readonly requestId?: string;

  constructor(status: number, body: ApiErrorBody) {
    super(body.message);
    this.name = "ApiError";
    this.status = status;
    this.code = body.error;
    this.details = body.details;
    this.requestId = body.request_id;
  }

  /** 4xx responses will fail identically on retry; 5xx and network errors may not. */
  get isRetryable(): boolean {
    return this.status >= 500 || this.status === 429;
  }
}

export interface RequestOptions extends Omit<RequestInit, "body"> {
  body?: unknown;
  /** Query parameters; undefined and null entries are dropped. */
  params?: Record<string, string | number | boolean | undefined | null>;
}

function buildUrl(path: string, params?: RequestOptions["params"]): string {
  const url = new URL(`${API_PREFIX}${path}`, BASE_URL);
  for (const [key, value] of Object.entries(params ?? {})) {
    if (value !== undefined && value !== null) {
      url.searchParams.set(key, String(value));
    }
  }
  return url.toString();
}

export async function apiFetch<T>(
  path: string,
  { body, params, headers, ...init }: RequestOptions = {},
): Promise<T> {
  let response: Response;
  try {
    response = await fetch(buildUrl(path, params), {
      ...init,
      // Sends the httpOnly refresh cookie once Phase 2 auth lands.
      credentials: "include",
      headers: {
        ...(body !== undefined ? { "Content-Type": "application/json" } : {}),
        ...headers,
      },
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
  } catch {
    // fetch only rejects on network-level failure; give that the same shape as
    // an API error so callers have exactly one error type to handle.
    throw new ApiError(0, {
      error: "network_error",
      message: "Could not reach the SecondBrain API. Is the backend running?",
    });
  }

  if (response.status === 204) {
    return undefined as T;
  }

  const payload: unknown = await response.json().catch(() => null);

  if (!response.ok) {
    const fallback: ApiErrorBody = {
      error: "unknown_error",
      message: response.statusText || "The request failed.",
    };
    throw new ApiError(response.status, (payload as ApiErrorBody) ?? fallback);
  }

  return payload as T;
}

export const api = {
  get: <T>(path: string, options?: RequestOptions) =>
    apiFetch<T>(path, { ...options, method: "GET" }),
  post: <T>(path: string, body?: unknown, options?: RequestOptions) =>
    apiFetch<T>(path, { ...options, method: "POST", body }),
  patch: <T>(path: string, body?: unknown, options?: RequestOptions) =>
    apiFetch<T>(path, { ...options, method: "PATCH", body }),
  delete: <T>(path: string, options?: RequestOptions) =>
    apiFetch<T>(path, { ...options, method: "DELETE" }),
};

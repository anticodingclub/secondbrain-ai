import {
  getAccessToken,
  refreshOnce,
  setAccessToken,
} from "@/lib/api/token-store";
import type { ApiErrorBody, TokenResponse } from "./types";

const BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const API_PREFIX = "/api/v1";

/** Endpoints that must never trigger the refresh-and-retry path. */
const AUTH_ENDPOINTS = new Set(["/auth/login", "/auth/register", "/auth/refresh"]);

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
  /** Escape hatch for the refresh call itself, which must not recurse. */
  skipAuthRetry?: boolean;
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

async function rawFetch(path: string, options: RequestOptions): Promise<Response> {
  // `skipAuthRetry` is ours, not fetch's — drop it before spreading into init.
  const { body, params, headers, skipAuthRetry, ...init } = options;
  void skipAuthRetry;
  const token = getAccessToken();
  try {
    return await fetch(buildUrl(path, params), {
      ...init,
      // Sends the httpOnly refresh cookie on the auth endpoints.
      credentials: "include",
      headers: {
        ...(body !== undefined ? { "Content-Type": "application/json" } : {}),
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
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
}

/**
 * Exchange the httpOnly refresh cookie for a fresh access token.
 *
 * Returns null rather than throwing when there is no usable session — that is
 * the ordinary state of a signed-out visitor, not an error.
 */
export async function refreshAccessToken(): Promise<string | null> {
  return refreshOnce(async () => {
    const response = await rawFetch("/auth/refresh", {
      method: "POST",
      skipAuthRetry: true,
    });
    if (!response.ok) {
      setAccessToken(null);
      return null;
    }
    const tokens = (await response.json()) as TokenResponse;
    setAccessToken(tokens.access_token);
    return tokens.access_token;
  });
}

async function parse<T>(response: Response): Promise<T> {
  if (response.status === 204) return undefined as T;

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

export async function apiFetch<T>(
  path: string,
  options: RequestOptions = {},
): Promise<T> {
  let response = await rawFetch(path, options);

  // A 401 usually just means the 30-minute access token aged out. Refresh once
  // and replay the request, so an expired token is invisible to the user rather
  // than an unexplained failure mid-session.
  const mayRetry =
    response.status === 401 && !options.skipAuthRetry && !AUTH_ENDPOINTS.has(path);

  if (mayRetry) {
    const token = await refreshAccessToken();
    if (token) {
      response = await rawFetch(path, { ...options, skipAuthRetry: true });
    }
  }

  return parse<T>(response);
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

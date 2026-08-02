import { QueryClient, isServer } from "@tanstack/react-query";

import { ApiError } from "@/lib/api/client";

function makeQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 30_000,
        gcTime: 5 * 60_000,
        refetchOnWindowFocus: false,
        retry: (failureCount, error) => {
          // Retrying a 401 or a 404 just delays the error the user needs to see.
          if (error instanceof ApiError && !error.isRetryable) return false;
          return failureCount < 2;
        },
      },
      mutations: { retry: false },
    },
  });
}

let browserQueryClient: QueryClient | undefined;

export function getQueryClient(): QueryClient {
  // A fresh client per server render keeps one user's cache out of another's
  // response; the browser reuses one so navigation stays instant.
  if (isServer) return makeQueryClient();
  browserQueryClient ??= makeQueryClient();
  return browserQueryClient;
}

export const queryKeys = {
  system: ["system"] as const,
  health: ["health"] as const,
  readiness: ["health", "ready"] as const,
} as const;

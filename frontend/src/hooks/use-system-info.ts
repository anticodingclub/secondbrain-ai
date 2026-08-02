"use client";

import { useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api/client";
import { queryKeys } from "@/lib/query-client";
import type { ReadinessResponse, SystemInfo } from "@/lib/api/types";

export function useSystemInfo() {
  return useQuery({
    queryKey: queryKeys.system,
    queryFn: () => api.get<SystemInfo>("/system"),
    // Provider config only changes on redeploy; no reason to refetch it often.
    staleTime: 5 * 60_000,
  });
}

export function useReadiness() {
  return useQuery({
    queryKey: queryKeys.readiness,
    queryFn: () => api.get<ReadinessResponse>("/health/ready"),
    refetchInterval: 30_000,
    staleTime: 0,
  });
}

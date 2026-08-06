"use client";

import { useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api/client";
import type { DashboardStats } from "@/lib/api/types";

export function useDashboard() {
  return useQuery({
    queryKey: ["dashboard"],
    queryFn: () => api.get<DashboardStats>("/dashboard"),
    // Documents index in the background, so the numbers move on their own
    // for a while after an upload.
    refetchInterval: (query) =>
      (query.state.data?.pending_count ?? 0) > 0 ? 3000 : false,
  });
}

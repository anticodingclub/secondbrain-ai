"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api/client";
import type { RepositoryRecord } from "@/lib/api/types";

const KEY = ["repositories"] as const;

export function useRepositories() {
  return useQuery({
    queryKey: KEY,
    queryFn: () => api.get<RepositoryRecord[]>("/repositories"),
    // Cloning and indexing take minutes, so poll while anything is in flight.
    refetchInterval: (query) =>
      query.state.data?.some((repo) =>
        ["pending", "cloning", "importing"].includes(repo.status),
      )
        ? 2000
        : false,
  });
}

export function useImportRepository() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (repository: string) =>
      api.post<RepositoryRecord>("/repositories", { repository }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: KEY }),
  });
}

export function useSyncRepository() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.post<RepositoryRecord>(`/repositories/${id}/sync`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: KEY }),
  });
}

export function useDeleteRepository() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.delete<void>(`/repositories/${id}`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: KEY }),
  });
}

"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  deleteDocument,
  getStorageUsage,
  listDocuments,
} from "@/lib/api/documents";
import type { DocumentFilters } from "@/lib/api/types";

/**
 * Query keys as data, so invalidation cannot drift from the keys in use.
 * `documentKeys.all` is a prefix, which invalidates every list and the usage
 * summary in one call.
 */
export const documentKeys = {
  all: ["documents"] as const,
  list: (filters: DocumentFilters) => ["documents", "list", filters] as const,
  usage: () => ["documents", "usage"] as const,
};

export function useDocuments(filters: DocumentFilters = {}) {
  return useQuery({
    queryKey: documentKeys.list(filters),
    queryFn: () => listDocuments(filters),
    // Keeps the previous page on screen while the next one loads, instead of
    // collapsing the table to a spinner on every filter keystroke.
    placeholderData: (previous) => previous,
  });
}

export function useStorageUsage() {
  return useQuery({
    queryKey: documentKeys.usage(),
    queryFn: getStorageUsage,
  });
}

export function useDeleteDocument() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: deleteDocument,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: documentKeys.all }),
  });
}

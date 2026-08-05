import { api } from "@/lib/api/client";
import type { SearchRequest, SearchResponse } from "@/lib/api/types";

export function search(request: SearchRequest): Promise<SearchResponse> {
  return api.post<SearchResponse>("/search", request);
}

/**
 * Contracts mirroring the FastAPI response models.
 *
 * Hand-written for now. Once the API surface grows past a handful of endpoints
 * these should be generated from /openapi.json so drift becomes a build error
 * rather than a runtime surprise.
 */

export interface ApiErrorBody {
  error: string;
  message: string;
  details?: Record<string, unknown>;
  request_id?: string;
}

export interface HealthResponse {
  status: "ok";
  version: string;
  environment: string;
}

export interface DependencyStatus {
  healthy: boolean;
  detail: string | null;
}

export interface ReadinessResponse {
  status: "ready" | "degraded";
  version: string;
  dependencies: Record<string, DependencyStatus>;
}

export interface SystemInfo {
  app_name: string;
  version: string;
  environment: string;
  embedding: {
    provider: string;
    model: string;
    dimensions: number;
  };
  vector_store: {
    backend: string;
    mode: string;
    collection: string;
  };
  llm_provider: string;
  llm_model: string;
  storage_backend: string;
}

// ─── Auth ───────────────────────────────────────────────────────────────────

export interface User {
  id: string;
  email: string;
  display_name: string;
  is_active: boolean;
  created_at: string;
}

/**
 * Note the absence of a refresh token: it lives in an httpOnly cookie that
 * JavaScript deliberately cannot read.
 */
export interface TokenResponse {
  access_token: string;
  token_type: string;
  expires_in: number;
  user: User;
}

export interface LoginPayload {
  email: string;
  password: string;
}

export interface RegisterPayload {
  email: string;
  password: string;
  display_name: string;
}

// ─── Documents ──────────────────────────────────────────────────────────────

export type DocumentStatus =
  | "pending"
  | "parsing"
  | "chunking"
  | "embedding"
  | "indexed"
  | "failed";

export type SourceType = "upload" | "folder_sync" | "github" | "url";

export interface DocumentRecord {
  id: string;
  title: string;
  original_filename: string;
  mime_type: string;
  extension: string;
  size_bytes: number;
  content_hash: string;
  status: DocumentStatus;
  source_type: SourceType;
  collection_id: string | null;
  error_message: string | null;
  page_count: number | null;
  word_count: number | null;
  chunk_count: number;
  language: string | null;
  doc_metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface UploadResponse {
  document: DocumentRecord;
  was_duplicate: boolean;
}

export interface Page<ItemT> {
  items: ItemT[];
  total: number;
  limit: number;
  offset: number;
}

export interface DocumentFilters {
  status?: DocumentStatus;
  extensions?: string[];
  collectionId?: string;
  search?: string;
  limit?: number;
  offset?: number;
}

export interface StorageUsage {
  document_count: number;
  total_bytes: number;
  max_upload_bytes: number;
}

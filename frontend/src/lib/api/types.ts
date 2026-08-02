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

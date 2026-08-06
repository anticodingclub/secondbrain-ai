/**
 * The build roadmap, and how far it has got.
 *
 * `COMPLETED_THROUGH_PHASE` is the single number to bump when a phase lands —
 * `done` is derived from it rather than tracked per row, so the dashboard
 * cannot drift out of step with reality the way a hand-maintained list of
 * booleans does.
 */

export const COMPLETED_THROUGH_PHASE = 8;

export interface RoadmapPhase {
  phase: number;
  title: string;
  done: boolean;
}

const PHASE_TITLES = [
  "Architecture & scaffold",
  "Authentication",
  "File uploads",
  "Document parsing & OCR",
  "Chunking & embeddings",
  "Vector & hybrid search",
  "RAG chat with citations",
  "Dashboard & analytics",
  "GitHub repository indexing",
  "Production deployment",
] as const;

export const ROADMAP: RoadmapPhase[] = PHASE_TITLES.map((title, index) => ({
  phase: index + 1,
  title,
  done: index + 1 <= COMPLETED_THROUGH_PHASE,
}));

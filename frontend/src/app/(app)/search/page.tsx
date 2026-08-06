"use client";

import { useMutation } from "@tanstack/react-query";
import { FileText, Search as SearchIcon, Sparkles } from "lucide-react";
import { type FormEvent, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { ApiError } from "@/lib/api/client";
import { openDocument } from "@/lib/api/documents";
import { search } from "@/lib/api/search";
import type { SearchHit, SearchMode, SearchResponse } from "@/lib/api/types";
import { cn } from "@/lib/utils";

const MODES: { value: SearchMode; label: string; hint: string }[] = [
  { value: "hybrid", label: "Hybrid", hint: "Meaning and exact terms together" },
  { value: "semantic", label: "Meaning", hint: "Finds ideas, not words" },
  { value: "keyword", label: "Exact", hint: "Finds literal terms and identifiers" },
];

const EXAMPLES = [
  "Where is my internship offer letter?",
  "What was the API endpoint in my backend project?",
  "Show notes where I discussed OAuth",
  "Find every mention of Docker",
];

/** Highlights query terms inside a snippet without using dangerouslySetInnerHTML. */
function Highlighted({ text, query }: { text: string; query: string }) {
  const terms = query
    .toLowerCase()
    .match(/[\w'-]+/g)
    ?.filter((term) => term.length > 2);

  if (!terms?.length) return <>{text}</>;

  // One pass, case-insensitive, escaping regex metacharacters in the terms.
  const pattern = new RegExp(
    `(${terms.map((term) => term.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|")})`,
    "gi",
  );

  return (
    <>
      {text.split(pattern).map((part, index) =>
        terms.includes(part.toLowerCase()) ? (
          <mark key={index} className="rounded bg-accent/25 px-0.5 text-foreground">
            {part}
          </mark>
        ) : (
          <span key={index}>{part}</span>
        ),
      )}
    </>
  );
}

function HitCard({ hit, query }: { hit: SearchHit; query: string }) {
  const location = [
    hit.page_number !== null ? `page ${hit.page_number}` : null,
    hit.section_title,
  ]
    .filter(Boolean)
    .join(" · ");

  return (
    <Card className="animate-fade-up transition-colors hover:border-border-strong">
      <CardContent className="space-y-2.5 p-4">
        <div className="flex items-start gap-3">
          <span className="mt-0.5 grid size-8 shrink-0 place-items-center rounded-sb bg-background-subtle text-subtle">
            <FileText className="size-4" />
          </span>

          <div className="min-w-0 flex-1">
            {/* A button, not a link: the content endpoint needs a Bearer
                token that a plain navigation cannot carry. */}
            <button
              type="button"
              onClick={() => void openDocument(hit.document_id)}
              className="block max-w-full truncate text-left text-sm font-medium hover:text-accent"
            >
              {hit.document_title || hit.filename}
            </button>
            {location && <p className="mt-0.5 text-xs text-subtle">{location}</p>}
          </div>

          <div className="flex shrink-0 items-center gap-1.5">
            {hit.matched_by.map((source) => (
              <Badge
                key={source}
                variant={source === "semantic" ? "accent" : "neutral"}
                title={
                  source === "semantic"
                    ? "Matched on meaning"
                    : "Matched the literal terms"
                }
              >
                {source === "semantic" ? "meaning" : "exact"}
              </Badge>
            ))}
          </div>
        </div>

        <p className="pl-11 text-sm leading-relaxed text-muted">
          <Highlighted text={hit.snippet} query={query} />
        </p>
      </CardContent>
    </Card>
  );
}

export default function SearchPage() {
  const [query, setQuery] = useState("");
  const [mode, setMode] = useState<SearchMode>("hybrid");
  const [submitted, setSubmitted] = useState("");

  const results = useMutation<SearchResponse, Error, { query: string; mode: SearchMode }>({
    mutationFn: (variables) => search({ query: variables.query, mode: variables.mode, limit: 20 }),
  });

  function run(nextQuery: string, nextMode: SearchMode = mode) {
    const trimmed = nextQuery.trim();
    if (!trimmed) return;
    setSubmitted(trimmed);
    results.mutate({ query: trimmed, mode: nextMode });
  }

  function onSubmit(event: FormEvent) {
    event.preventDefault();
    run(query);
  }

  return (
    <div className="mx-auto max-w-3xl px-4 py-10 md:px-8">
      <header className="animate-fade-up">
        <h1 className="text-2xl font-semibold tracking-tight">Search</h1>
        <p className="mt-1.5 text-sm text-muted">
          Ask in plain language. Answers come from your own documents.
        </p>
      </header>

      <form onSubmit={onSubmit} className="animate-fade-up mt-6">
        <div className="relative">
          <SearchIcon className="pointer-events-none absolute left-3.5 top-1/2 size-4 -translate-y-1/2 text-subtle" />
          <Input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Where is my internship offer letter?"
            aria-label="Search your documents"
            autoFocus
            className="h-12 pl-10 pr-24 text-base"
          />
          <Button
            type="submit"
            variant="primary"
            disabled={!query.trim() || results.isPending}
            className="absolute right-1.5 top-1/2 -translate-y-1/2"
          >
            {results.isPending ? "Searching…" : "Search"}
          </Button>
        </div>

        <div className="mt-3 flex flex-wrap items-center gap-1.5">
          {MODES.map((option) => (
            <button
              key={option.value}
              type="button"
              title={option.hint}
              onClick={() => {
                setMode(option.value);
                if (submitted) run(submitted, option.value);
              }}
              className={cn(
                "rounded-full border px-3 py-1 text-xs transition-colors",
                mode === option.value
                  ? "border-accent/40 bg-accent/10 text-accent"
                  : "border-border text-subtle hover:border-border-strong hover:text-foreground",
              )}
            >
              {option.label}
            </button>
          ))}
          {results.data && (
            <span className="ml-auto text-xs text-subtle">
              {results.data.total} {results.data.total === 1 ? "result" : "results"} ·{" "}
              {results.data.took_ms} ms
            </span>
          )}
        </div>
      </form>

      <section className="mt-8 space-y-2.5">
        {results.isPending && (
          <>
            {[0, 1, 2].map((index) => (
              <Card key={index}>
                <CardContent className="space-y-2 p-4">
                  <Skeleton className="h-4 w-56" />
                  <Skeleton className="h-3 w-full" />
                  <Skeleton className="h-3 w-4/5" />
                </CardContent>
              </Card>
            ))}
          </>
        )}

        {results.isError && (
          <p
            role="alert"
            className="rounded-sb border border-danger/40 bg-danger/10 px-3 py-2 text-sm text-danger"
          >
            {results.error instanceof ApiError
              ? results.error.message
              : "Search failed. Please try again."}
          </p>
        )}

        {results.data?.hits.map((hit) => (
          <HitCard key={hit.chunk_id} hit={hit} query={submitted} />
        ))}

        {results.data && results.data.hits.length === 0 && (
          <div className="py-12 text-center">
            <p className="text-sm text-muted">
              Nothing matched &ldquo;{submitted}&rdquo;.
            </p>
            <p className="mt-1 text-xs text-subtle">
              Only documents that finished indexing are searchable.
            </p>
          </div>
        )}

        {!results.data && !results.isPending && (
          <div className="animate-fade-up py-8">
            <p className="flex items-center gap-2 text-xs font-medium text-subtle">
              <Sparkles className="size-3.5" />
              Try asking
            </p>
            <div className="mt-3 flex flex-wrap gap-2">
              {EXAMPLES.map((example) => (
                <button
                  key={example}
                  type="button"
                  onClick={() => {
                    setQuery(example);
                    run(example);
                  }}
                  className="rounded-full border border-border px-3 py-1.5 text-xs text-muted transition-colors hover:border-border-strong hover:text-foreground"
                >
                  {example}
                </button>
              ))}
            </div>
          </div>
        )}
      </section>
    </div>
  );
}

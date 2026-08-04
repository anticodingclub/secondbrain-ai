"use client";

import { Boxes, Cpu, Database, HardDrive } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { useReadiness, useSystemInfo } from "@/hooks/use-system-info";
import { ROADMAP } from "@/lib/roadmap";
import { cn } from "@/lib/utils";

function StatCard({
  icon: Icon,
  label,
  value,
  detail,
  loading,
}: {
  icon: typeof Cpu;
  label: string;
  value?: string;
  detail?: string;
  loading: boolean;
}) {
  return (
    <Card className="animate-fade-up">
      <CardHeader className="flex items-center gap-2.5">
        <Icon className="size-4 text-subtle" />
        <CardTitle className="text-muted">{label}</CardTitle>
      </CardHeader>
      <CardContent>
        {loading ? (
          <>
            <Skeleton className="h-6 w-28" />
            <Skeleton className="mt-2 h-3 w-20" />
          </>
        ) : (
          <>
            <p className="truncate text-lg font-medium tracking-tight">
              {value ?? "—"}
            </p>
            {detail && <p className="mt-1 text-xs text-subtle">{detail}</p>}
          </>
        )}
      </CardContent>
    </Card>
  );
}

export default function DashboardPage() {
  const system = useSystemInfo();
  const readiness = useReadiness();

  return (
    <div className="mx-auto max-w-5xl px-4 py-10 md:px-8">
      <header className="animate-fade-up">
        <h1 className="text-2xl font-semibold tracking-tight">
          Your second brain
        </h1>
        <p className="mt-1.5 max-w-xl text-sm text-muted">
          Ask questions in plain language and get answers from everything you
          own — with citations back to the exact page.
        </p>
      </header>

      {system.isError && (
        <Card className="mt-8 border-danger/40 bg-danger/5">
          <CardContent className="p-5">
            <p className="text-sm font-medium text-danger">
              Cannot reach the API
            </p>
            <p className="mt-1 text-sm text-muted">
              Start the backend and this page will connect automatically.
            </p>
            <code className="mt-3 block overflow-x-auto rounded-lg border border-border bg-background px-3 py-2 font-mono text-xs text-muted">
              uvicorn app.main:create_app --factory --reload
            </code>
          </CardContent>
        </Card>
      )}

      <section className="mt-8 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard
          icon={Cpu}
          label="Embedding model"
          value={system.data?.embedding.model.split("/").at(-1)}
          detail={
            system.data && `${system.data.embedding.dimensions}-d vectors`
          }
          loading={system.isLoading}
        />
        <StatCard
          icon={Boxes}
          label="Vector store"
          value={system.data?.vector_store.backend}
          detail={system.data && `${system.data.vector_store.mode} mode`}
          loading={system.isLoading}
        />
        <StatCard
          icon={Cpu}
          label="Language model"
          value={system.data?.llm_model}
          detail={system.data && `via ${system.data.llm_provider}`}
          loading={system.isLoading}
        />
        <StatCard
          icon={HardDrive}
          label="Storage"
          value={system.data?.storage_backend}
          detail={system.data?.environment}
          loading={system.isLoading}
        />
      </section>

      <section className="mt-10">
        <h2 className="text-sm font-medium text-muted">Dependencies</h2>
        <Card className="animate-fade-up mt-3">
          <CardContent className="divide-y divide-border p-0">
            {readiness.isLoading ? (
              <div className="space-y-3 p-5">
                <Skeleton className="h-4 w-40" />
                <Skeleton className="h-4 w-40" />
              </div>
            ) : readiness.isError ? (
              <p className="p-5 text-sm text-subtle">Unavailable.</p>
            ) : (
              Object.entries(readiness.data?.dependencies ?? {}).map(
                ([name, status]) => (
                  <div
                    key={name}
                    className="flex items-center justify-between px-5 py-3.5"
                  >
                    <span className="flex items-center gap-2.5 text-sm">
                      <Database className="size-4 text-subtle" />
                      {name.replace(/_/g, " ")}
                    </span>
                    <Badge variant={status.healthy ? "success" : "danger"}>
                      {status.healthy ? "healthy" : (status.detail ?? "down")}
                    </Badge>
                  </div>
                ),
              )
            )}
          </CardContent>
        </Card>
      </section>

      <section className="mt-10">
        <h2 className="text-sm font-medium text-muted">Roadmap</h2>
        <ol className="animate-fade-up mt-3 grid gap-2 sm:grid-cols-2">
          {ROADMAP.map(({ phase, title, done }) => (
            <li
              key={phase}
              className={cn(
                "flex items-center gap-3 rounded-sb border border-border px-4 py-3 text-sm",
                done ? "bg-surface/60" : "text-subtle",
              )}
            >
              <span
                className={cn(
                  "grid size-6 shrink-0 place-items-center rounded-full text-[11px] font-medium tabular-nums",
                  done
                    ? "bg-accent text-accent-contrast"
                    : "border border-border text-subtle",
                )}
              >
                {phase}
              </span>
              {title}
              {done && (
                <Badge variant="accent" className="ml-auto">
                  done
                </Badge>
              )}
            </li>
          ))}
        </ol>
      </section>
    </div>
  );
}

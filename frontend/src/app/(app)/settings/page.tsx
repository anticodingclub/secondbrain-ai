"use client";

import { LogOut, ShieldOff } from "lucide-react";
import { useState } from "react";

import { useAuth } from "@/components/auth-provider";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useSystemInfo } from "@/hooks/use-system-info";

function Row({ label, value }: { label: string; value: string | undefined }) {
  return (
    <div className="flex items-center justify-between gap-4 px-5 py-3.5 text-sm">
      <span className="text-muted">{label}</span>
      <span className="truncate font-mono text-xs">{value ?? "—"}</span>
    </div>
  );
}

export default function SettingsPage() {
  const { user, logout, logoutEverywhere } = useAuth();
  const system = useSystemInfo();
  const [isEndingSessions, setIsEndingSessions] = useState(false);

  return (
    <div className="mx-auto max-w-3xl px-4 py-10 md:px-8">
      <header className="animate-fade-up">
        <h1 className="text-2xl font-semibold tracking-tight">Settings</h1>
        <p className="mt-1.5 text-sm text-muted">
          Your account and this instance&rsquo;s configuration.
        </p>
      </header>

      <section className="mt-8">
        <h2 className="text-sm font-medium text-muted">Account</h2>
        <Card className="animate-fade-up mt-3">
          <CardContent className="divide-y divide-border p-0">
            <Row label="Name" value={user?.display_name} />
            <Row label="Email" value={user?.email} />
            <Row
              label="Member since"
              value={
                user
                  ? new Date(user.created_at).toLocaleDateString(undefined, {
                      year: "numeric",
                      month: "long",
                      day: "numeric",
                    })
                  : undefined
              }
            />
          </CardContent>
        </Card>
      </section>

      <section className="mt-8">
        <h2 className="text-sm font-medium text-muted">Sessions</h2>
        <Card className="animate-fade-up mt-3">
          <CardHeader>
            <CardTitle>Sign out</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <p className="text-sm text-muted">
              Signing out everywhere revokes every refresh token on every device.
              Use it if you think a session has been compromised.
            </p>
            <div className="flex flex-wrap gap-2">
              <Button onClick={() => void logout()}>
                <LogOut />
                Sign out
              </Button>
              <Button
                variant="danger"
                disabled={isEndingSessions}
                onClick={() => {
                  setIsEndingSessions(true);
                  void logoutEverywhere().finally(() => setIsEndingSessions(false));
                }}
              >
                <ShieldOff />
                {isEndingSessions ? "Revoking…" : "Sign out everywhere"}
              </Button>
            </div>
          </CardContent>
        </Card>
      </section>

      <section className="mt-8">
        <h2 className="text-sm font-medium text-muted">This instance</h2>
        <Card className="animate-fade-up mt-3">
          <CardContent className="divide-y divide-border p-0">
            <Row label="Version" value={system.data?.version} />
            <Row label="Environment" value={system.data?.environment} />
            <Row label="Embedding model" value={system.data?.embedding.model} />
            <Row
              label="Vector store"
              value={
                system.data &&
                `${system.data.vector_store.backend} (${system.data.vector_store.mode})`
              }
            />
            <Row
              label="Language model"
              value={
                system.data && `${system.data.llm_model} via ${system.data.llm_provider}`
              }
            />
            <Row label="Storage" value={system.data?.storage_backend} />
          </CardContent>
        </Card>
      </section>
    </div>
  );
}

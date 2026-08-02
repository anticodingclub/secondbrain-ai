"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { type FormEvent, useState } from "react";

import { useAuth } from "@/components/auth-provider";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Field } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { ApiError } from "@/lib/api/client";

const MIN_PASSWORD_LENGTH = 8;

/** Maps the backend's 422 field errors onto the inputs that caused them. */
function fieldErrorsFrom(error: ApiError): Record<string, string> {
  const raw = error.details?.errors;
  if (!Array.isArray(raw)) return {};

  const mapped: Record<string, string> = {};
  for (const item of raw as Array<{ loc?: unknown[]; msg?: string }>) {
    const field = item.loc?.at(-1);
    if (typeof field === "string" && item.msg) mapped[field] = item.msg;
  }
  return mapped;
}

export default function RegisterPage() {
  const { register } = useAuth();
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [isSubmitting, setIsSubmitting] = useState(false);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setFieldErrors({});
    setIsSubmitting(true);

    const form = new FormData(event.currentTarget);

    try {
      await register({
        email: String(form.get("email")),
        password: String(form.get("password")),
        display_name: String(form.get("display_name")),
      });
      router.replace("/");
    } catch (cause) {
      if (cause instanceof ApiError) {
        const perField = fieldErrorsFrom(cause);
        setFieldErrors(perField);
        // Only show the banner when nothing landed on a specific input, so
        // the same problem is not reported twice.
        if (Object.keys(perField).length === 0) setError(cause.message);
      } else {
        setError("Something went wrong. Please try again.");
      }
      setIsSubmitting(false);
    }
  }

  return (
    <Card>
      <CardContent className="p-6 pt-6">
        <h2 className="text-base font-medium">Create your second brain</h2>
        <p className="mt-1 text-sm text-muted">
          Your documents stay on this machine.
        </p>

        <form onSubmit={onSubmit} className="mt-6 space-y-4" noValidate>
          <Field label="Name" htmlFor="display_name" error={fieldErrors.display_name}>
            <Input
              id="display_name"
              name="display_name"
              autoComplete="name"
              required
              autoFocus
              placeholder="Ada Lovelace"
              aria-invalid={Boolean(fieldErrors.display_name)}
              aria-describedby={fieldErrors.display_name ? "display_name-error" : undefined}
            />
          </Field>

          <Field label="Email" htmlFor="email" error={fieldErrors.email}>
            <Input
              id="email"
              name="email"
              type="email"
              autoComplete="email"
              required
              placeholder="you@example.com"
              aria-invalid={Boolean(fieldErrors.email)}
              aria-describedby={fieldErrors.email ? "email-error" : undefined}
            />
          </Field>

          <Field
            label="Password"
            htmlFor="password"
            error={fieldErrors.password}
            hint={`At least ${MIN_PASSWORD_LENGTH} characters.`}
          >
            <Input
              id="password"
              name="password"
              type="password"
              autoComplete="new-password"
              required
              minLength={MIN_PASSWORD_LENGTH}
              placeholder="••••••••"
              aria-invalid={Boolean(fieldErrors.password)}
              aria-describedby={
                fieldErrors.password ? "password-error" : "password-hint"
              }
            />
          </Field>

          {error && (
            <p
              role="alert"
              className="rounded-sb border border-danger/40 bg-danger/10 px-3 py-2 text-xs text-danger"
            >
              {error}
            </p>
          )}

          <Button
            type="submit"
            variant="primary"
            className="w-full"
            disabled={isSubmitting}
          >
            {isSubmitting ? "Creating account…" : "Create account"}
          </Button>
        </form>

        <p className="mt-5 text-center text-sm text-muted">
          Already have an account?{" "}
          <Link href="/login" className="text-accent hover:underline">
            Sign in
          </Link>
        </p>
      </CardContent>
    </Card>
  );
}

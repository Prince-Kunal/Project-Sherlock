"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense } from "react";

import { Button, buttonVariants } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { ApiError } from "@/lib/api";
import { googleSignInUrl, useAuthConfig, useDevLogin } from "@/lib/auth";

const ERRORS: Record<string, string> = {
  not_allowed:
    "This Google account isn't on Sherlock's invite list. Ask the owner to add you.",
  denied: "Google sign-in was cancelled.",
  state: "That sign-in link expired or was tampered with. Try again.",
  expired: "The sign-in took too long. Try again.",
  unverified: "Google hasn't verified this account's email address.",
  google: "Google returned an error. Try again in a minute.",
};

export default function LoginPage() {
  return (
    <main className="flex flex-1 items-center justify-center p-6">
      <Card className="w-full max-w-sm">
        <CardHeader>
          <CardTitle className="text-2xl">Sherlock</CardTitle>
          <CardDescription>
            Referrals for fresh openings, one reviewed email at a time.
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          <Suspense>
            <SignInError />
          </Suspense>
          <SignInButtons />
        </CardContent>
      </Card>
    </main>
  );
}

function SignInError() {
  const error = useSearchParams().get("error");
  if (!error) return null;
  return (
    <p className="text-destructive text-sm">
      {ERRORS[error] ?? "Sign-in failed. Try again."}
    </p>
  );
}

function SignInButtons() {
  const router = useRouter();
  const config = useAuthConfig();
  const devLogin = useDevLogin();
  const disabled =
    devLogin.error instanceof ApiError && devLogin.error.status === 404;

  if (config.isPending) {
    return <p className="text-muted-foreground text-sm">Loading…</p>;
  }
  if (config.isError) {
    return (
      <p className="text-destructive text-sm">
        Could not reach the Sherlock API.
      </p>
    );
  }

  return (
    <>
      {config.data.google && (
        <a href={googleSignInUrl()} className={buttonVariants({ size: "lg" })}>
          Sign in with Google
        </a>
      )}
      {config.data.google && (
        <p className="text-muted-foreground text-xs">
          Google will ask to let Sherlock send email as you and read your mail.
          It only opens the threads of emails it sent, to spot replies, and
          nothing is sent without your approval.
        </p>
      )}
      {config.data.dev_login && (
        <Button
          variant={config.data.google ? "outline" : "default"}
          size="lg"
          disabled={devLogin.isPending}
          onClick={() =>
            devLogin.mutate(undefined, {
              onSuccess: () => router.replace("/review"),
            })
          }
        >
          {devLogin.isPending ? "Signing in…" : "Dev login"}
        </Button>
      )}
      {devLogin.isError && (
        <p className="text-destructive text-sm">
          {disabled
            ? "Dev login is disabled on this server (DEV_AUTH=false)."
            : "Could not sign in. Is the backend running?"}
        </p>
      )}
      {!config.data.google && !config.data.dev_login && (
        <p className="text-muted-foreground text-sm">
          No sign-in method is set up. Set GOOGLE_CLIENT_ID and
          GOOGLE_CLIENT_SECRET on the server.
        </p>
      )}
    </>
  );
}

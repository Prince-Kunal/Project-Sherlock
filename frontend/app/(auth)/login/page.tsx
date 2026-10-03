"use client";

import { useRouter } from "next/navigation";

import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { ApiError } from "@/lib/api";
import { useDevLogin } from "@/lib/auth";

export default function LoginPage() {
  const router = useRouter();
  const devLogin = useDevLogin();

  const signIn = () =>
    devLogin.mutate(undefined, { onSuccess: () => router.replace("/review") });

  const disabled =
    devLogin.error instanceof ApiError && devLogin.error.status === 404;

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
          <Button onClick={signIn} disabled={devLogin.isPending} size="lg">
            {devLogin.isPending ? "Signing in…" : "Dev login"}
          </Button>
          {devLogin.isError && (
            <p className="text-destructive text-sm">
              {disabled
                ? "Dev login is disabled on this server (DEV_AUTH=false)."
                : "Could not sign in. Is the backend running?"}
            </p>
          )}
          <p className="text-muted-foreground text-xs">
            Google sign-in arrives in Phase 7.
          </p>
        </CardContent>
      </Card>
    </main>
  );
}

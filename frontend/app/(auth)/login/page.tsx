"use client";

import Image from "next/image";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense } from "react";

import { CanonLine, Wordmark } from "@/components/brand";
import { Button, buttonVariants } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { ApiError } from "@/lib/api";
import { googleSignInUrl, useAuthConfig, useDevLogin } from "@/lib/auth";
import { CANON } from "@/lib/canon";
import { cn } from "@/lib/utils";
import portrait from "@/public/paget/portrait.webp";

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
    <main
      id="main"
      className="grain grid min-h-[100dvh] flex-1 md:grid-cols-[1.1fr_1fr]"
    >
      <section className="bg-muted/50 relative hidden flex-col justify-between overflow-hidden border-r p-10 md:flex lg:p-14">
        <Link
          href="/"
          className="focus-visible:ring-ring/60 w-fit rounded-lg outline-none focus-visible:ring-3"
        >
          <Wordmark />
        </Link>
        <div className="paget-tonal-plate mx-auto w-full max-w-[560px] [mask-image:radial-gradient(ellipse_52%_54%_at_52%_50%,black_45%,transparent_100%)]">
          <Image
            src={portrait}
            alt="Sidney Paget's portrait of Sherlock Holmes, pipe in hand."
            priority
            sizes="(min-width: 768px) 45vw, 0px"
            placeholder="blur"
            className="h-auto w-full"
          />
        </div>
        <CanonLine {...CANON.observe} />
      </section>

      <section className="flex flex-col justify-center px-6 py-12 sm:px-12">
        <div className="mx-auto w-full max-w-sm">
          <Link
            href="/"
            className="focus-visible:ring-ring/60 mb-12 inline-block rounded-lg outline-none focus-visible:ring-3 md:hidden"
          >
            <Wordmark />
          </Link>
          <h1 className="text-4xl leading-[1.02] font-semibold tracking-[-0.04em]">
            Back to Baker Street.
          </h1>
          <p className="text-muted-foreground mt-3 leading-relaxed">
            Sherlock is invite only. Sign in with the Google account you were
            invited with.
          </p>
          <div className="mt-8 flex flex-col gap-3">
            <Suspense>
              <SignInError />
            </Suspense>
            <SignInButtons />
          </div>
        </div>
      </section>
    </main>
  );
}

function SignInError() {
  const error = useSearchParams().get("error");
  if (!error) return null;
  return (
    <p
      role="alert"
      className="border-destructive/25 bg-destructive/[0.06] text-destructive rounded-2xl border px-4 py-3 text-sm"
    >
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
    return (
      <div role="status" aria-label="Loading sign-in options">
        <Skeleton className="h-11 w-full rounded-full" />
      </div>
    );
  }
  if (config.isError) {
    return (
      <p className="text-destructive text-sm">
        Can&apos;t reach the Sherlock API. Is the backend running?
      </p>
    );
  }

  return (
    <>
      {config.data.google && (
        <>
          <a
            href={googleSignInUrl()}
            className={cn(buttonVariants({ size: "lg" }), "w-full")}
          >
            Sign in with Google
          </a>
          <p className="text-muted-foreground text-xs leading-relaxed">
            Google will ask to let Sherlock send email as you and read your
            mail. It only opens the threads of emails it sent, to spot replies,
            and nothing is sent without your approval.
          </p>
        </>
      )}
      {config.data.dev_login && (
        <Button
          variant="outline"
          size="lg"
          className="w-full"
          disabled={devLogin.isPending}
          onClick={() =>
            devLogin.mutate(undefined, {
              onSuccess: () => router.replace("/review"),
            })
          }
        >
          {devLogin.isPending ? "Signing in…" : "Dev login (local only)"}
        </Button>
      )}
      {devLogin.isError && (
        <p className="text-destructive text-sm">
          {disabled
            ? "Dev login is disabled on this server (DEV_AUTH=false)."
            : "Couldn't sign in. Is the backend running?"}
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

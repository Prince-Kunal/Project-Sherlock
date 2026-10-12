"use client";

import { useQueryClient } from "@tanstack/react-query";
import { Check } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { Wordmark } from "@/components/brand";
import { PreferencesForm } from "@/components/profile/preferences-form";
import { ResumeEditor } from "@/components/profile/resume-editor";
import { UploadCard } from "@/components/profile/upload-card";
import { HunterKeyCard } from "@/components/settings/hunter-key-card";
import { LlmKeyCard } from "@/components/settings/llm-key-card";
import { Button, buttonVariants } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { ApiError, errorMessage } from "@/lib/api";
import { googleSignInUrl, useMe } from "@/lib/auth";
import {
  useCompleteOnboarding,
  useHunterKey,
  useLlmKey,
  useOnboarding,
  usePreferences,
  useResume,
} from "@/lib/queries";
import type { OnboardingStatus } from "@/lib/types";
import { cn } from "@/lib/utils";

const STEPS = [
  "Sign in",
  "Connect Gmail",
  "Add your keys",
  "Upload resume",
  "Check your resume",
  "Preferences",
  "First run",
] as const;

/** Where to resume after a reload: the first step the data doesn't satisfy yet. */
function firstOpenStep(s: OnboardingStatus): number {
  if (s.google_sign_in && !s.gmail) return 1;
  if (!s.llm_key) return 2;
  if (!s.resume) return 3;
  if (!s.preferences) return 4;
  return 6;
}

function Stepper({ step }: { step: number }) {
  return (
    <ol className="flex flex-wrap gap-x-4 gap-y-2 text-sm">
      {STEPS.map((label, i) => (
        <li
          key={label}
          aria-current={i === step ? "step" : undefined}
          className={cn(
            "flex items-center gap-1.5",
            i === step
              ? "text-foreground font-medium"
              : "text-muted-foreground",
          )}
        >
          <span
            className={cn(
              "flex size-5 items-center justify-center rounded-full text-[0.7rem] ring-1",
              i < step
                ? "bg-primary text-primary-foreground ring-primary"
                : i === step
                  ? "ring-foreground"
                  : "ring-border",
            )}
          >
            {i < step ? <Check className="size-3" /> : i + 1}
          </span>
          {label}
        </li>
      ))}
    </ol>
  );
}

function StepCard({
  title,
  description,
  children,
}: {
  title: string;
  description: React.ReactNode;
  children?: React.ReactNode;
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>{title}</CardTitle>
        <CardDescription>{description}</CardDescription>
      </CardHeader>
      {children && <CardContent>{children}</CardContent>}
    </Card>
  );
}

export default function WelcomePage() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const me = useMe();
  const status = useOnboarding();
  const resume = useResume();
  const prefs = usePreferences();
  const llmKey = useLlmKey();
  const hunterKey = useHunterKey();
  const complete = useCompleteOnboarding();
  // Until the user moves, the step is the first one the data doesn't satisfy (resumes after a reload).
  const [chosen, setStep] = useState<number | null>(null);
  const step = chosen ?? (status.data ? firstOpenStep(status.data) : null);

  const unauthenticated =
    me.error instanceof ApiError && me.error.status === 401;
  useEffect(() => {
    if (unauthenticated) router.replace("/login");
  }, [unauthenticated, router]);

  const go = (next: number) => {
    void queryClient.invalidateQueries({ queryKey: ["onboarding"] });
    setStep(next);
    window.scrollTo({ top: 0 });
  };
  const finish = (start: boolean) =>
    complete.mutate(start, {
      onSuccess: () => router.replace("/review"),
    });

  if (step === null || !status.data || !me.data) {
    return (
      <div className="mx-auto flex w-full max-w-3xl flex-col gap-6 px-4 py-8">
        <Wordmark />
        <Skeleton className="h-8 w-80" />
        <Skeleton className="h-64 w-full rounded-2xl" />
      </div>
    );
  }

  // Keys and resume come from their own queries so a step unlocks as soon as it's saved.
  const s: OnboardingStatus = {
    ...status.data,
    llm_key: llmKey.data
      ? llmKey.data.configured || llmKey.data.owner_fallback_allowed
      : status.data.llm_key,
    hunter_key: hunterKey.data
      ? hunterKey.data.configured || hunterKey.data.owner_fallback_allowed
      : status.data.hunter_key,
    resume: resume.data !== undefined ? !!resume.data : status.data.resume,
  };
  const prefsReady =
    !!prefs.data &&
    prefs.data.target_roles.length > 0 &&
    prefs.data.employment_types.length > 0;
  const back =
    step > 1 ? (
      <Button variant="ghost" onClick={() => go(step - 1)}>
        Back
      </Button>
    ) : null;

  return (
    <div className="mx-auto flex w-full max-w-3xl flex-col gap-6 px-4 py-8">
      <div className="flex items-center justify-between gap-4">
        <Wordmark />
        <Button
          variant="ghost"
          size="sm"
          disabled={complete.isPending}
          onClick={() => finish(false)}
        >
          Skip setup
        </Button>
      </div>
      <div>
        <h1 className="text-3xl font-semibold tracking-[-0.03em]">
          Welcome{me.data.name ? `, ${me.data.name.split(" ")[0]}` : ""}
        </h1>
        <p className="text-muted-foreground mt-1.5 max-w-[60ch]">
          A few steps and Sherlock starts finding openings and people who can
          refer you. Nothing is ever sent without your approval.
        </p>
      </div>
      <Stepper step={step} />

      {step === 1 && (
        <StepCard
          title="Connect Gmail"
          description="Approved emails go out from your own Gmail, and Sherlock watches those threads for replies. It can send and read mail, nothing else, and you can disconnect any time in Settings."
        >
          <div className="flex flex-wrap items-center gap-3">
            {!s.google_sign_in ? (
              <p className="text-muted-foreground text-sm">
                Google sign-in isn&apos;t set up on this server, so emails go to
                a fake mailbox. Carry on.
              </p>
            ) : s.gmail ? (
              <p className="flex items-center gap-1.5 text-sm">
                <Check className="size-4" /> Gmail is connected.
              </p>
            ) : (
              <a
                href={googleSignInUrl("/welcome")}
                className={buttonVariants()}
              >
                Connect Gmail
              </a>
            )}
            <Button
              variant={s.gmail || !s.google_sign_in ? "default" : "ghost"}
              onClick={() => go(2)}
            >
              {s.gmail || !s.google_sign_in ? "Continue" : "Do this later"}
            </Button>
          </div>
        </StepCard>
      )}

      {step === 2 && (
        <>
          <LlmKeyCard />
          <HunterKeyCard />
          <div className="flex items-center justify-between gap-3">
            {back}
            <div className="flex items-center gap-3">
              {!s.hunter_key && s.llm_key && (
                <span className="text-muted-foreground text-sm">
                  Without a Hunter key Sherlock can&apos;t find people to email.
                </span>
              )}
              <Button disabled={!s.llm_key} onClick={() => go(3)}>
                Continue
              </Button>
            </div>
          </div>
        </>
      )}

      {step === 3 && (
        <>
          <UploadCard hasResume={!!resume.data} disabled={!s.llm_key} />
          <div className="flex items-center justify-between gap-3">
            {back}
            <Button disabled={!resume.data} onClick={() => go(4)}>
              Continue
            </Button>
          </div>
        </>
      )}

      {step === 4 && resume.data && (
        <>
          <StepCard
            title="Check what Sherlock read"
            description="Your master resume is the only source for tailored copies: nothing that isn't here will ever appear on one. Fix anything misread and save, then continue."
          />
          <ResumeEditor current={resume.data} />
          <div className="flex items-center justify-between gap-3">
            {back}
            <Button onClick={() => go(5)}>Looks right</Button>
          </div>
        </>
      )}

      {step === 5 && (
        <>
          <PreferencesForm />
          <div className="flex items-center justify-between gap-3">
            {back}
            <div className="flex items-center gap-3">
              {!prefsReady && (
                <span className="text-muted-foreground text-sm">
                  Add at least one target role and employment type, then save.
                </span>
              )}
              <Button disabled={!prefsReady} onClick={() => go(6)}>
                Continue
              </Button>
            </div>
          </div>
        </>
      )}

      {step === 6 && (
        <StepCard
          title="Start Sherlock"
          description="Sherlock scores the latest openings against your resume, finds someone to ask at the best ones, and puts drafts in your review queue. This takes a few minutes. After today it runs every morning at 07:00."
        >
          <div className="flex flex-col gap-3">
            <ul className="text-muted-foreground flex flex-col gap-1 text-sm">
              <li>
                Gmail:{" "}
                {s.gmail
                  ? "connected"
                  : s.google_sign_in
                    ? "not connected (connect it before approving emails)"
                    : "fake mailbox"}
              </li>
              <li>Gemini key: {s.llm_key ? "added" : "missing"}</li>
              <li>
                Hunter key:{" "}
                {s.hunter_key ? "added" : "missing (no contacts until added)"}
              </li>
              <li>Resume: {s.resume ? "uploaded" : "missing"}</li>
            </ul>
            <div className="flex flex-wrap items-center gap-3">
              {back}
              <Button
                disabled={!s.llm_key || !s.resume || complete.isPending}
                onClick={() => finish(true)}
              >
                {complete.isPending ? "Starting…" : "Start the first run"}
              </Button>
              <Button
                variant="ghost"
                disabled={complete.isPending}
                onClick={() => finish(false)}
              >
                Finish without running
              </Button>
            </div>
            {complete.isError && (
              <p className="text-destructive text-sm">
                {errorMessage(complete.error)}
              </p>
            )}
          </div>
        </StepCard>
      )}
    </div>
  );
}

"use client";

import { CheckCircle2, Loader2 } from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useRef } from "react";

import { PageHeader } from "@/components/page-header";
import { buttonVariants } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { errorMessage } from "@/lib/api";
import { useAddJobUrl } from "@/lib/queries";

/** Where the "Send to Sherlock" browser extension lands: adds the job at ?url= once, then says how it went. */
function AddJob() {
  const url = useSearchParams().get("url") ?? "";
  const add = useAddJobUrl();
  const started = useRef(false);
  const valid = /^https?:\/\//i.test(url);

  useEffect(() => {
    if (valid && !started.current) {
      started.current = true;
      add.mutate(url);
    }
  }, [valid, url, add]);

  if (!valid) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>No job link</CardTitle>
          <CardDescription>
            Open a job posting and click the Sherlock button in your browser, or
            paste a link on the Jobs page.
          </CardDescription>
        </CardHeader>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          {add.isPending && <Loader2 className="size-4 animate-spin" />}
          {add.isSuccess && <CheckCircle2 className="size-4" />}
          {add.isPending
            ? "Adding the job…"
            : add.isSuccess
              ? "Added to Sherlock"
              : add.isError
                ? "Couldn't add this job"
                : "Adding the job…"}
        </CardTitle>
        <CardDescription className="break-all">{url}</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        {add.isSuccess && (
          <p className="text-sm">
            <span className="font-medium">{add.data.title}</span> at{" "}
            {add.data.company.name}
            {add.data.location ? ` · ${add.data.location}` : ""}. It&apos;s
            scored against your resume with the next matching run; you can also
            refresh matches on the Jobs page now.
          </p>
        )}
        {add.isError && (
          <p className="text-destructive text-sm">{errorMessage(add.error)}</p>
        )}
        <div className="flex flex-wrap gap-2">
          <Link href="/jobs" className={buttonVariants({ size: "sm" })}>
            Go to Jobs
          </Link>
          {add.isError && (
            <button
              type="button"
              className={buttonVariants({ size: "sm", variant: "outline" })}
              onClick={() => add.mutate(url)}
            >
              Try again
            </button>
          )}
        </div>
      </CardContent>
    </Card>
  );
}

export default function AddJobPage() {
  return (
    <div className="flex max-w-2xl flex-col gap-6">
      <PageHeader
        title="Send to Sherlock"
        description="A job from your browser, added to your list."
      />
      <Suspense fallback={null}>
        <AddJob />
      </Suspense>
    </div>
  );
}

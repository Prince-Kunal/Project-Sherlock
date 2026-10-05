"use client";

import { CheckCircle2, XCircle } from "lucide-react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { errorMessage } from "@/lib/api";
import { useAtsCheck } from "@/lib/queries";

export function PreviewPanel({ version }: { version: number }) {
  const ats = useAtsCheck(version);

  return (
    <div className="flex flex-col gap-4">
      {ats.isPending && (
        <p className="text-muted-foreground text-sm">Rendering and checking…</p>
      )}
      {ats.isError && (
        <p className="text-destructive text-sm">{errorMessage(ats.error)}</p>
      )}
      {ats.data &&
        (ats.data.passed ? (
          <Alert>
            <CheckCircle2 />
            <AlertTitle>ATS check passed</AlertTitle>
            <AlertDescription>
              One page, single column, real selectable text: applicant tracking
              systems will read every line of this PDF.
            </AlertDescription>
          </Alert>
        ) : (
          <Alert variant="destructive">
            <XCircle />
            <AlertTitle>ATS check failed</AlertTitle>
            <AlertDescription>
              <ul className="list-disc pl-4">
                {ats.data.failures.map((f) => (
                  <li key={f}>{f}</li>
                ))}
              </ul>
              {ats.data.page_count > 1 && (
                <p className="mt-2">
                  Your full master resume is longer than one page. That&apos;s
                  fine here: each tailored resume picks only the most relevant
                  bullets and is trimmed to one page.
                </p>
              )}
            </AlertDescription>
          </Alert>
        ))}
      <iframe
        title="Resume preview"
        src={`/api/resume/preview.pdf?version=${version}`}
        className="h-[80vh] w-full rounded-lg border"
      />
    </div>
  );
}

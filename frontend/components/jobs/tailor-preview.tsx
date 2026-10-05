"use client";

import { CheckCircle2, ExternalLink, FileText, XCircle } from "lucide-react";
import { useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { errorMessage } from "@/lib/api";
import { useTailorPreview } from "@/lib/queries";
import type { ResumeChange, TailorPreview } from "@/lib/types";

const CHANGE_LABELS: Record<ResumeChange["change"], string> = {
  rephrased: "Rephrased",
  reordered: "Moved up or down",
  removed: "Left out",
  added: "Added",
};

/** Temporary (PLAN.md Phase 4): tailor the resume to this match and show the result. */
export function TailorPreviewButton({ matchId }: { matchId: string }) {
  const preview = useTailorPreview();

  return (
    <div className="mt-2">
      <Button
        variant="outline"
        size="sm"
        disabled={preview.isPending}
        onClick={() => preview.mutate(matchId)}
      >
        <FileText />
        {preview.isPending
          ? "Tailoring… (about 10–30 s)"
          : preview.data
            ? "Tailor again"
            : "Preview tailored resume"}
      </Button>
      {preview.isError && (
        <p className="text-destructive mt-2 text-sm">
          {errorMessage(preview.error)}
        </p>
      )}
      {preview.data && (
        <PreviewResult result={preview.data} version={preview.submittedAt} />
      )}
    </div>
  );
}

function PreviewResult({
  result,
  version,
}: {
  result: TailorPreview;
  version: number;
}) {
  const [showChanges, setShowChanges] = useState(false);
  const coverage = result.keyword_coverage;
  const total = coverage.matched.length + coverage.missing.length;
  const counts = result.diff.reduce<Record<string, number>>((acc, c) => {
    acc[c.change] = (acc[c.change] ?? 0) + 1;
    return acc;
  }, {});
  // Cache-bust so "Tailor again" shows the new file.
  const pdfSrc = `/api${result.pdf_url}?v=${version}`;

  return (
    <div className="bg-muted/30 mt-3 flex flex-col gap-3 rounded-lg border p-3">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2 text-sm">
        <span className="inline-flex items-center gap-1.5 font-medium">
          {result.ats.passed ? (
            <CheckCircle2 className="size-4 text-emerald-600" />
          ) : (
            <XCircle className="text-destructive size-4" />
          )}
          ATS check {result.ats.passed ? "passed" : "failed"} ·{" "}
          {result.ats.page_count} page
        </span>
        {total > 0 && (
          <span>
            ATS match: {coverage.matched.length}/{total} must-haves
          </span>
        )}
        <a
          href={pdfSrc}
          target="_blank"
          rel="noreferrer"
          className="inline-flex items-center gap-1 underline underline-offset-4"
        >
          Open {result.filename}
          <ExternalLink className="size-3" />
        </a>
      </div>

      {coverage.missing.length > 0 && (
        <div className="flex flex-wrap items-center gap-1.5 text-xs">
          <span className="text-muted-foreground">
            Not on your resume (genuine gaps, never added):
          </span>
          {coverage.missing.map((k) => (
            <Badge
              key={k}
              variant="outline"
              className="text-muted-foreground border-dashed"
            >
              {k}
            </Badge>
          ))}
        </div>
      )}

      <div className="text-sm">
        <button
          type="button"
          className="text-muted-foreground hover:text-foreground text-xs underline-offset-4 hover:underline"
          aria-expanded={showChanges}
          onClick={() => setShowChanges((s) => !s)}
        >
          {result.diff.length === 0
            ? "No changes from your master resume"
            : `Changes from your master resume: ${Object.entries(counts)
                .map(
                  ([k, n]) =>
                    `${n} ${CHANGE_LABELS[k as ResumeChange["change"]].toLowerCase()}`,
                )
                .join(", ")}`}
          {result.bullets_dropped_to_fit > 0 &&
            ` (${result.bullets_dropped_to_fit} left out to fit one page)`}
        </button>
        {showChanges && (
          <ul className="mt-2 flex flex-col gap-2">
            {result.diff.map((c) => (
              <li
                key={c.bullet_id}
                className="bg-background rounded-md border p-2"
              >
                <span className="text-muted-foreground text-xs">
                  {CHANGE_LABELS[c.change]}
                </span>
                {c.change === "rephrased" ? (
                  <>
                    <p className="text-muted-foreground line-through decoration-1">
                      {c.before}
                    </p>
                    <p>{c.after}</p>
                  </>
                ) : (
                  <p
                    className={
                      c.change === "removed"
                        ? "text-muted-foreground"
                        : undefined
                    }
                  >
                    {c.before}
                  </p>
                )}
              </li>
            ))}
          </ul>
        )}
      </div>

      <iframe
        title="Tailored resume"
        src={pdfSrc}
        className="h-[70vh] w-full rounded-md border bg-white"
      />
    </div>
  );
}

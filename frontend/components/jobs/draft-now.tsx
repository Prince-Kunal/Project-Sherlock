"use client";

import { ArrowRight, Sparkles } from "lucide-react";
import Link from "next/link";

import { Button } from "@/components/ui/button";
import { errorMessage } from "@/lib/api";
import { useDraftNow } from "@/lib/queries";
import type { Match } from "@/lib/types";

/** Phase 6 "manual pipeline": find a contact, tailor the resume and write the email now. */
export function DraftNowButton({ match }: { match: Match }) {
  const draft = useDraftNow();
  const status = draft.data?.status ?? match.outreach?.status;

  if (status === "pending_review") {
    return (
      <Link
        href="/review"
        className="mt-2 inline-flex items-center gap-1 text-sm font-medium underline-offset-4 hover:underline"
      >
        Draft ready in the review queue <ArrowRight className="size-3.5" />
      </Link>
    );
  }
  if (status && status !== "drafting" && status !== "failed") return null;

  return (
    <div className="mt-2">
      <Button
        size="sm"
        disabled={draft.isPending}
        onClick={() => draft.mutate(match.id)}
        title="Find a contact, tailor your resume and write the email now"
      >
        <Sparkles />
        {draft.isPending
          ? "Drafting… (about 30 s)"
          : status === "failed"
            ? "Try drafting again"
            : "Draft now"}
      </Button>
      {draft.isError && (
        <p className="text-destructive mt-1 text-sm">
          {errorMessage(draft.error)}
        </p>
      )}
    </div>
  );
}

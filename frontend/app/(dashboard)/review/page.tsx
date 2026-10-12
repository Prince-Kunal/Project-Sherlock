"use client";

import { PageHeader } from "@/components/page-header";
import { ReviewQueue } from "@/components/review/review-queue";

export default function ReviewPage() {
  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Review queue"
        description={
          <>
            Every email waits for your approval. Keys: <Kbd>j</Kbd> <Kbd>k</Kbd>{" "}
            to move, <Kbd>a</Kbd> to approve, <Kbd>s</Kbd> to skip.
          </>
        }
      />
      <ReviewQueue />
    </div>
  );
}

function Kbd({ children }: { children: React.ReactNode }) {
  return (
    <kbd className="bg-muted text-foreground ring-foreground/10 rounded-md px-1.5 py-0.5 font-mono text-xs ring-1 ring-inset">
      {children}
    </kbd>
  );
}

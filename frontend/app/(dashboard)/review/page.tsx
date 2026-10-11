"use client";

import { ReviewQueue } from "@/components/review/review-queue";

export default function ReviewPage() {
  return (
    <div className="flex flex-col gap-4">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Review queue</h1>
        <p className="text-muted-foreground text-sm">
          Every email needs your approval before it goes out.
        </p>
      </div>
      <ReviewQueue />
    </div>
  );
}

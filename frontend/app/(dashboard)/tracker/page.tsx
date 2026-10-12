"use client";

import { OutreachTracker } from "@/components/tracker/outreach-tracker";

export default function TrackerPage() {
  return (
    <div className="flex flex-col gap-4">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">
          Outreach tracker
        </h1>
        <p className="text-muted-foreground text-sm">
          Everything you&apos;ve approved: what&apos;s queued, sent, answered
          and how it turned out.
        </p>
      </div>
      <OutreachTracker />
    </div>
  );
}

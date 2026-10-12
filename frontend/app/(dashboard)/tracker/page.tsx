"use client";

import { PageHeader } from "@/components/page-header";
import { OutreachTracker } from "@/components/tracker/outreach-tracker";

export default function TrackerPage() {
  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Outreach tracker"
        description="Every case you've approved: queued, sent, answered, and how it turned out."
      />
      <OutreachTracker />
    </div>
  );
}

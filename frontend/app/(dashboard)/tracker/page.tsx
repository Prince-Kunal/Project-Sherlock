"use client";

import { useState } from "react";

import { PageHeader } from "@/components/page-header";
import { AnalyticsPanel } from "@/components/tracker/analytics-panel";
import { OutreachTracker } from "@/components/tracker/outreach-tracker";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";

export default function TrackerPage() {
  const [tab, setTab] = useState("outreach");
  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Outreach tracker"
        description="Every case you've approved: queued, sent, answered, and how it turned out."
      />
      <Tabs value={tab} onValueChange={(v) => setTab(String(v))}>
        <TabsList>
          <TabsTrigger value="outreach">Outreach</TabsTrigger>
          <TabsTrigger value="insights">What&apos;s working</TabsTrigger>
        </TabsList>
        <TabsContent value="outreach" className="pt-4">
          <OutreachTracker />
        </TabsContent>
        <TabsContent value="insights" className="pt-4">
          <AnalyticsPanel />
        </TabsContent>
      </Tabs>
    </div>
  );
}

"use client";

import { RefreshCw } from "lucide-react";
import { useState } from "react";

import { PageHeader } from "@/components/page-header";
import { AddJobUrl } from "@/components/jobs/add-job-url";
import { AllJobs } from "@/components/jobs/all-jobs";
import { MatchesList } from "@/components/jobs/matches-list";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useMe } from "@/lib/auth";
import { usePollNow } from "@/lib/queries";

export default function JobsPage() {
  const me = useMe();
  const poll = usePollNow();
  const [tab, setTab] = useState("matches");

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Jobs"
        description="Fresh openings, scored against your resume and preferences."
        actions={
          <>
            {me.data?.is_admin && (
              <Button
                variant="ghost"
                disabled={poll.isPending || poll.isSuccess}
                onClick={() => poll.mutate()}
                title="Ask the worker to poll every source now"
              >
                <RefreshCw />{" "}
                {poll.isSuccess ? "Poll queued" : "Poll sources now"}
              </Button>
            )}
            <AddJobUrl />
          </>
        }
      />

      <Tabs value={tab} onValueChange={(v) => setTab(String(v))}>
        <TabsList>
          <TabsTrigger value="matches">Matches</TabsTrigger>
          <TabsTrigger value="all">All jobs</TabsTrigger>
        </TabsList>
        <TabsContent value="matches" className="pt-2">
          <MatchesList />
        </TabsContent>
        <TabsContent value="all" className="pt-2">
          <AllJobs />
        </TabsContent>
      </Tabs>
    </div>
  );
}

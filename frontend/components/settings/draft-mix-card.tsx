"use client";

import { useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { errorMessage } from "@/lib/api";
import { usePreferences, useSavePreferences } from "@/lib/queries";

/** How the daily batch is split between job-linked and open outreach (PLAN.md Phase 8). */
export function DraftMixCard() {
  const prefs = usePreferences();
  const save = useSavePreferences();
  const [share, setShare] = useState<number | null>(null);
  const saved = prefs.data?.open_outreach_share ?? 40;
  const value = share ?? saved;
  const batch = prefs.data?.daily_draft_batch ?? 0;
  const open = Math.round((batch * value) / 100);

  return (
    <Card>
      <CardHeader>
        <CardTitle>Daily draft mix</CardTitle>
        <CardDescription>
          How each day&apos;s drafts are split between jobs that are posted and
          open outreach to your target companies. If one side runs short, the
          other fills the gap.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        <div className="flex items-center justify-between text-sm">
          <span>Job-linked {100 - value}%</span>
          <span>Open outreach {value}%</span>
        </div>
        <input
          type="range"
          aria-label="Open outreach share"
          min={0}
          max={100}
          step={10}
          value={value}
          disabled={!prefs.data}
          onChange={(e) => setShare(e.target.valueAsNumber)}
          className="accent-primary w-full"
        />
        {prefs.data && (
          <p className="text-muted-foreground text-sm">
            Of your {batch} drafts a day: about {batch - open} job-linked and{" "}
            {open} open outreach. Change the number of drafts under Schedule
            above.
          </p>
        )}
        <div className="flex items-center gap-3">
          <Button
            disabled={!prefs.data || value === saved || save.isPending}
            onClick={() =>
              prefs.data &&
              save.mutate(
                { ...prefs.data, open_outreach_share: value },
                { onSuccess: () => setShare(null) },
              )
            }
          >
            {save.isPending ? "Saving…" : "Save"}
          </Button>
          {save.isError && (
            <p className="text-destructive text-sm">
              {errorMessage(save.error)}
            </p>
          )}
        </div>
      </CardContent>
    </Card>
  );
}

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
import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";
import { errorMessage } from "@/lib/api";
import { usePreferences, useSavePreferences } from "@/lib/queries";
import type { SourceFeed } from "@/lib/types";

const FEEDS: { value: SourceFeed; label: string; hint: string }[] = [
  {
    value: "boards",
    label: "Company career pages",
    hint: "Greenhouse, Lever, Ashby, SmartRecruiters, Workable and Recruitee boards of the companies Sherlock watches. The most reliable source.",
  },
  {
    value: "adzuna",
    label: "Adzuna",
    hint: "Job search across Indian job sites, searched with your target roles. Short descriptions.",
  },
  {
    value: "hn",
    label: "Hacker News: Who is hiring",
    hint: "The monthly thread. Many startups, often remote, sometimes with the founder's email.",
  },
  {
    value: "remotive",
    label: "Remotive",
    hint: "Remote jobs worldwide (listed by Remotive, linked back to it). Mostly roles open to other regions, so fewer fit an India-based search.",
  },
];

/** Phase 10: which sources feed your matches. Jobs you add by link always count. */
export function SourcesCard() {
  const prefs = usePreferences();
  const save = useSavePreferences();
  const [chosen, setChosen] = useState<SourceFeed[] | null>(null);
  const saved = prefs.data?.job_sources ?? [];
  const value = chosen ?? saved;
  const changed =
    chosen !== null && [...chosen].sort().join() !== [...saved].sort().join();

  return (
    <Card>
      <CardHeader>
        <CardTitle>Job sources</CardTitle>
        <CardDescription>
          Where your matches come from. Jobs you add by link (or with the
          browser extension) always count.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        {FEEDS.map((feed) => (
          <Label key={feed.value} className="items-start gap-2.5 font-normal">
            <Checkbox
              className="mt-0.5"
              checked={value.includes(feed.value)}
              disabled={!prefs.data}
              onCheckedChange={(on) =>
                setChosen(
                  on
                    ? [...new Set([...value, feed.value])]
                    : value.filter((f) => f !== feed.value),
                )
              }
            />
            <span className="flex flex-col gap-0.5">
              <span className="text-sm font-medium">{feed.label}</span>
              <span className="text-muted-foreground text-xs">{feed.hint}</span>
            </span>
          </Label>
        ))}
        {value.length === 0 && (
          <p className="text-sm text-amber-700 dark:text-amber-400">
            With nothing ticked, only jobs you add yourself are matched.
          </p>
        )}
        <div className="flex items-center gap-3">
          <Button
            disabled={!prefs.data || !changed || save.isPending}
            onClick={() =>
              prefs.data &&
              save.mutate(
                { ...prefs.data, job_sources: value },
                { onSuccess: () => setChosen(null) },
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

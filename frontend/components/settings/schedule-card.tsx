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
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { errorMessage } from "@/lib/api";
import { usePreferences, useSavePreferences } from "@/lib/queries";
import { type Preferences, pickPreferences } from "@/lib/types";

const MAX_SEND_CAP = 30;
const SCHEDULE_KEYS = [
  "daily_draft_batch",
  "daily_send_cap",
  "followup_after_days",
  "send_window_start",
  "send_window_end",
  "timezone",
] as const;

function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <Label className="flex flex-col items-stretch gap-1 font-normal">
      <span className="text-sm">{label}</span>
      {children}
      {hint && <span className="text-muted-foreground text-xs">{hint}</span>}
    </Label>
  );
}

function ScheduleFields({ initial }: { initial: Preferences }) {
  const latest = usePreferences().data ?? initial;
  const save = useSavePreferences();
  const [p, setP] = useState(initial);
  const set = (patch: Partial<Preferences>) =>
    setP((cur) => ({ ...cur, ...patch }));
  const number = (value: number) => (Number.isNaN(value) ? "" : value);
  const windowOk =
    p.send_window_start.slice(0, 5) < p.send_window_end.slice(0, 5);

  return (
    <form
      className="flex flex-col gap-5"
      onSubmit={(e) => {
        e.preventDefault();
        // Only this card's fields, on top of what's saved (the pause switch may have changed).
        save.mutate({ ...latest, ...pickPreferences(p, SCHEDULE_KEYS) });
      }}
    >
      <div className="grid gap-4 sm:grid-cols-3">
        <Field label="Drafts per day" hint="New drafts added each morning">
          <Input
            type="number"
            min={0}
            max={30}
            value={number(p.daily_draft_batch)}
            onChange={(e) => set({ daily_draft_batch: e.target.valueAsNumber })}
          />
        </Field>
        <Field label="Daily send cap" hint={`Hard maximum ${MAX_SEND_CAP}`}>
          <Input
            type="number"
            min={0}
            max={MAX_SEND_CAP}
            value={number(p.daily_send_cap)}
            onChange={(e) => set({ daily_send_cap: e.target.valueAsNumber })}
          />
        </Field>
        <Field
          label="Follow up after (days)"
          hint="One follow-up at most, if there's no reply"
        >
          <Input
            type="number"
            min={1}
            max={30}
            value={number(p.followup_after_days)}
            onChange={(e) =>
              set({ followup_after_days: e.target.valueAsNumber })
            }
          />
        </Field>
      </div>
      <div className="grid gap-4 sm:grid-cols-3">
        <Field label="Send window starts">
          <Input
            type="time"
            value={p.send_window_start.slice(0, 5)}
            onChange={(e) => set({ send_window_start: e.target.value })}
          />
        </Field>
        <Field label="Send window ends">
          <Input
            type="time"
            value={p.send_window_end.slice(0, 5)}
            onChange={(e) => set({ send_window_end: e.target.value })}
          />
        </Field>
        <Field label="Timezone" hint="Drafts arrive at 07:00 here">
          <Input
            value={p.timezone}
            onChange={(e) => set({ timezone: e.target.value })}
          />
        </Field>
      </div>
      {!windowOk && (
        <p className="text-destructive text-sm">
          The send window must end after it starts.
        </p>
      )}
      <div className="flex items-center justify-end gap-3">
        {save.isError && (
          <span className="text-destructive text-sm">
            {errorMessage(save.error)}
          </span>
        )}
        {save.isSuccess && (
          <span className="text-muted-foreground text-sm">Saved</span>
        )}
        <Button type="submit" disabled={save.isPending || !windowOk}>
          {save.isPending ? "Saving…" : "Save schedule"}
        </Button>
      </div>
    </form>
  );
}

/** Phase 9: how much Sherlock drafts and sends, and when. */
export function ScheduleCard() {
  const prefs = usePreferences();
  return (
    <Card>
      <CardHeader>
        <CardTitle>Schedule</CardTitle>
        <CardDescription>
          How many drafts you get each morning, how many emails may go out a
          day, and when. Emails only go out on weekdays inside the window.
        </CardDescription>
      </CardHeader>
      <CardContent>
        {prefs.isError && (
          <p className="text-destructive text-sm">
            {errorMessage(prefs.error)}
          </p>
        )}
        {prefs.data && <ScheduleFields initial={prefs.data} />}
      </CardContent>
    </Card>
  );
}

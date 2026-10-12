"use client";

import { useState } from "react";

import { ChipsInput } from "@/components/chips-input";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { errorMessage } from "@/lib/api";
import { usePreferences, useSavePreferences } from "@/lib/queries";
import {
  type Preferences,
  pickPreferences,
  SETTINGS_PREFERENCE_KEYS,
} from "@/lib/types";

function toggle<T>(list: T[], item: T, on: boolean): T[] {
  return on ? [...new Set([...list, item])] : list.filter((x) => x !== item);
}

function NumberField({
  label,
  hint,
  value,
  min,
  max,
  onChange,
}: {
  label: string;
  hint?: string;
  value: number;
  min: number;
  max: number;
  onChange: (value: number) => void;
}) {
  return (
    <Label className="flex flex-col items-stretch gap-1 font-normal">
      <span className="text-sm">{label}</span>
      <Input
        type="number"
        min={min}
        max={max}
        value={Number.isNaN(value) ? "" : value}
        onChange={(e) => onChange(e.target.valueAsNumber)}
      />
      {hint && <span className="text-muted-foreground text-xs">{hint}</span>}
    </Label>
  );
}

function PreferencesFields({ initial }: { initial: Preferences }) {
  const latest = usePreferences().data ?? initial;
  const save = useSavePreferences();
  const [p, setP] = useState(initial);
  const set = (patch: Partial<Preferences>) =>
    setP((cur) => ({ ...cur, ...patch }));

  return (
    <form
      className="flex flex-col gap-6"
      onSubmit={(e) => {
        e.preventDefault();
        // Schedule, pause and draft mix are edited in Settings; keep what's saved there.
        save.mutate({
          ...p,
          ...pickPreferences(latest, SETTINGS_PREFERENCE_KEYS),
        });
      }}
    >
      <div className="grid gap-4 sm:grid-cols-2">
        <div className="flex flex-col gap-1">
          <span className="text-sm">Target roles</span>
          <ChipsInput
            ariaLabel="Target roles"
            placeholder="Backend Engineer Intern"
            value={p.target_roles}
            onChange={(target_roles) => set({ target_roles })}
          />
        </div>
        <div className="flex flex-col gap-1">
          <span className="text-sm">Locations</span>
          <ChipsInput
            ariaLabel="Locations"
            placeholder="Bengaluru"
            value={p.locations}
            onChange={(locations) => set({ locations })}
          />
        </div>
      </div>

      <div className="flex flex-wrap gap-x-8 gap-y-3">
        <fieldset className="flex flex-col gap-2">
          <legend className="mb-1 text-sm">Employment type</legend>
          {(
            [
              ["internship", "Internship"],
              ["full_time", "Full-time"],
            ] as const
          ).map(([value, label]) => (
            <Label key={value} className="font-normal">
              <Checkbox
                checked={p.employment_types.includes(value)}
                onCheckedChange={(on) =>
                  set({
                    employment_types: toggle(p.employment_types, value, on),
                  })
                }
              />
              {label}
            </Label>
          ))}
        </fieldset>
        <fieldset className="flex flex-col gap-2">
          <legend className="mb-1 text-sm">Company stage</legend>
          {(
            [
              ["startup", "Startup"],
              ["mid", "Mid-size"],
              ["large", "Large"],
            ] as const
          ).map(([value, label]) => (
            <Label key={value} className="font-normal">
              <Checkbox
                checked={p.company_stages.includes(value)}
                onCheckedChange={(on) =>
                  set({ company_stages: toggle(p.company_stages, value, on) })
                }
              />
              {label}
            </Label>
          ))}
        </fieldset>
        <Label className="items-start font-normal">
          <Switch
            checked={p.remote_ok}
            onCheckedChange={(remote_ok) => set({ remote_ok })}
          />
          Remote is fine
        </Label>
      </div>

      <div className="grid gap-4 sm:grid-cols-2">
        <NumberField
          label="Minimum fit score"
          hint="0–100"
          min={0}
          max={100}
          value={p.min_fit_score}
          onChange={(min_fit_score) => set({ min_fit_score })}
        />
        <NumberField
          label="Max job age (days)"
          min={1}
          max={60}
          value={p.max_job_age_days}
          onChange={(max_job_age_days) => set({ max_job_age_days })}
        />
      </div>

      <Label className="flex flex-col items-stretch gap-1 font-normal">
        <span className="text-sm">About me</span>
        <Textarea
          rows={3}
          maxLength={300}
          placeholder="One or two lines used in your emails, e.g. what you study and what you like building."
          value={p.about_me}
          onChange={(e) => set({ about_me: e.target.value })}
        />
        <span className="text-muted-foreground self-end text-xs">
          {p.about_me.length}/300
        </span>
      </Label>

      <div className="flex items-center justify-end gap-3">
        {save.isError && (
          <span className="text-destructive text-sm">
            {errorMessage(save.error)}
          </span>
        )}
        {save.isSuccess && (
          <span className="text-muted-foreground text-sm">Saved</span>
        )}
        <Button type="submit" disabled={save.isPending}>
          {save.isPending ? "Saving…" : "Save preferences"}
        </Button>
      </div>
    </form>
  );
}

export function PreferencesForm() {
  const prefs = usePreferences();
  return (
    <Card>
      <CardHeader>
        <CardTitle>Preferences</CardTitle>
        <CardDescription>
          What Sherlock looks for. How much it drafts and sends, and when, is
          under Settings → Schedule.
        </CardDescription>
      </CardHeader>
      <CardContent>
        {prefs.isError && (
          <p className="text-destructive text-sm">
            {errorMessage(prefs.error)}
          </p>
        )}
        {prefs.data && <PreferencesFields initial={prefs.data} />}
      </CardContent>
    </Card>
  );
}

"use client";

import { Plus } from "lucide-react";
import { useState } from "react";

import { ChipsInput } from "@/components/chips-input";
import { CompanyPicker } from "@/components/targets/company-picker";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { errorMessage } from "@/lib/api";
import {
  useDeleteTarget,
  useProspectOptions,
  useSaveTarget,
} from "@/lib/queries";
import type { CompanyBrief, CompanySize, ProspectTarget } from "@/lib/types";

const SIZES: { value: CompanySize; label: string }[] = [
  { value: "startup", label: "Startup (≤ 50)" },
  { value: "mid", label: "Mid-size (51–500)" },
  { value: "large", label: "Large (500+)" },
];

type Draft = Omit<ProspectTarget, "id" | "created_at">;

export const EMPTY_TARGET: Draft = {
  name: "",
  target_roles: [],
  contact_titles: ["CTO", "Engineering Manager"],
  industries: [],
  locations: [],
  company_sizes: ["startup"],
  include_companies: [],
  exclude_companies: [],
  is_active: true,
};

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
    <div className="flex flex-col gap-1.5">
      <span className="text-sm font-medium">{label}</span>
      {children}
      {hint && <span className="text-muted-foreground text-xs">{hint}</span>}
    </div>
  );
}

/** Create or edit one prospect target. */
export function TargetForm({
  target,
  onDone,
}: {
  target: ProspectTarget | null;
  onDone: () => void;
}) {
  const [t, setT] = useState<Draft>(target ?? EMPTY_TARGET);
  const set = (patch: Partial<Draft>) =>
    setT((prev) => ({ ...prev, ...patch }));
  const save = useSaveTarget();
  const remove = useDeleteTarget();
  const options = useProspectOptions();
  const suggestions = (options.data?.industries ?? [])
    .filter((i) => !t.industries.some((x) => x.toLowerCase() === i))
    .slice(0, 16);
  const ids = (companies: CompanyBrief[]) => companies.map((c) => c.id);

  return (
    <form
      className="flex flex-col gap-5"
      onSubmit={(e) => {
        e.preventDefault();
        save.mutate(
          {
            ...t,
            id: target?.id,
            include_companies: ids(t.include_companies),
            exclude_companies: ids(t.exclude_companies),
          },
          { onSuccess: onDone },
        );
      }}
    >
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Name" hint="Only you see this.">
          <Input
            value={t.name}
            placeholder="e.g. Bengaluru fintech startups"
            onChange={(e) => set({ name: e.target.value })}
          />
        </Field>
        <Field
          label="Roles you're after"
          hint="Shapes your resume and the ask. Empty: your preferences' roles."
        >
          <ChipsInput
            ariaLabel="Target roles"
            value={t.target_roles}
            placeholder="e.g. Backend Intern"
            onChange={(target_roles) => set({ target_roles })}
          />
        </Field>
        <Field
          label="Who to email"
          hint="People with these titles are picked first."
        >
          <ChipsInput
            ariaLabel="Contact titles"
            value={t.contact_titles}
            placeholder="e.g. CTO, Engineering Manager"
            onChange={(contact_titles) => set({ contact_titles })}
          />
        </Field>
        <Field
          label="Locations"
          hint='Cities or countries, or "Remote". Empty: anywhere.'
        >
          <ChipsInput
            ariaLabel="Locations"
            value={t.locations}
            placeholder="e.g. India, Remote"
            onChange={(locations) => set({ locations })}
          />
        </Field>
      </div>

      <Field label="Industries" hint="Empty: any industry.">
        <ChipsInput
          ariaLabel="Industries"
          value={t.industries}
          placeholder="e.g. Fintech, Developer Tools"
          onChange={(industries) => set({ industries })}
        />
        {suggestions.length > 0 && (
          <div className="flex flex-wrap gap-1">
            {suggestions.map((s) => (
              <Button
                key={s}
                type="button"
                variant="ghost"
                size="xs"
                onClick={() => set({ industries: [...t.industries, s] })}
              >
                <Plus /> {s}
              </Button>
            ))}
          </div>
        )}
      </Field>

      <Field label="Company size">
        <div className="flex flex-wrap gap-4">
          {SIZES.map(({ value, label }) => (
            <Label key={value} className="font-normal">
              <Checkbox
                checked={t.company_sizes.includes(value)}
                onCheckedChange={(on) =>
                  set({
                    company_sizes: on
                      ? [...new Set([...t.company_sizes, value])]
                      : t.company_sizes.filter((x) => x !== value),
                  })
                }
              />
              {label}
            </Label>
          ))}
        </div>
      </Field>

      <div className="grid gap-4 sm:grid-cols-2">
        <Field
          label="Always include"
          hint="Considered even outside the filters above."
        >
          <CompanyPicker
            ariaLabel="Companies to include"
            value={t.include_companies}
            onChange={(include_companies) => set({ include_companies })}
          />
        </Field>
        <Field label="Never include">
          <CompanyPicker
            ariaLabel="Companies to exclude"
            value={t.exclude_companies}
            onChange={(exclude_companies) => set({ exclude_companies })}
          />
        </Field>
      </div>

      <div className="flex flex-wrap items-center justify-between gap-3 border-t pt-4">
        <Label className="font-normal">
          <Switch
            checked={t.is_active}
            onCheckedChange={(is_active) => set({ is_active })}
          />
          Active
        </Label>
        <div className="flex flex-wrap gap-2">
          {target && (
            <Button
              type="button"
              variant="ghost"
              disabled={remove.isPending}
              onClick={() => remove.mutate(target.id, { onSuccess: onDone })}
            >
              Delete
            </Button>
          )}
          <Button type="button" variant="outline" onClick={onDone}>
            Cancel
          </Button>
          <Button type="submit" disabled={!t.name.trim() || save.isPending}>
            {save.isPending ? "Saving…" : "Save target"}
          </Button>
        </div>
      </div>
      {(save.isError || remove.isError) && (
        <p className="text-destructive text-sm">
          {errorMessage(save.error ?? remove.error)}
        </p>
      )}
    </form>
  );
}

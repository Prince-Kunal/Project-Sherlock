"use client";

import { ExternalLink } from "lucide-react";
import { useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { errorMessage } from "@/lib/api";
import { age, selectClass, SOURCE_LABELS, TYPE_LABELS } from "@/lib/jobs";
import { useJobs } from "@/lib/queries";
import type { EmploymentType, JobFilters } from "@/lib/types";

const PAGE_SIZE = 50;

/** Every fresh job, unscored: the raw feed behind the matches. */
export function AllJobs() {
  const [search, setSearch] = useState("");
  const [filters, setFilters] = useState<JobFilters>({
    limit: PAGE_SIZE,
    offset: 0,
  });
  const jobs = useJobs(filters);
  const update = (patch: Partial<JobFilters>) =>
    setFilters((f) => ({ ...f, ...patch, offset: 0 }));

  const total = jobs.data?.total ?? 0;
  const maxAge = jobs.data?.max_age_days ?? 14;

  return (
    <div className="flex flex-col gap-4">
      <form
        className="flex flex-wrap items-end gap-3"
        onSubmit={(e) => {
          e.preventDefault();
          update({ q: search.trim() || undefined });
        }}
      >
        <Input
          aria-label="Search jobs"
          placeholder="Search title, company, location"
          className="w-full sm:w-72"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          onBlur={() => update({ q: search.trim() || undefined })}
        />
        <Label className="flex flex-col items-start gap-1 font-normal">
          <span className="text-muted-foreground text-xs">Posted within</span>
          <select
            aria-label="Maximum age"
            className={selectClass}
            value={filters.max_age_days ?? maxAge}
            onChange={(e) => update({ max_age_days: Number(e.target.value) })}
          >
            {[1, 3, 7, 14, 30, 60]
              .filter((d) => d <= maxAge)
              .map((d) => (
                <option key={d} value={d}>
                  {d === 1 ? "1 day" : `${d} days`}
                </option>
              ))}
          </select>
        </Label>
        <Label className="flex flex-col items-start gap-1 font-normal">
          <span className="text-muted-foreground text-xs">Type</span>
          <select
            aria-label="Employment type"
            className={selectClass}
            value={filters.employment_type ?? ""}
            onChange={(e) =>
              update({
                employment_type: (e.target.value || undefined) as
                  EmploymentType | undefined,
              })
            }
          >
            <option value="">All types</option>
            {Object.entries(TYPE_LABELS).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </Label>
        <Label className="h-8 font-normal">
          <Switch
            checked={filters.remote === true}
            onCheckedChange={(on) => update({ remote: on ? true : undefined })}
          />
          Remote only
        </Label>
      </form>

      {jobs.isError && (
        <p className="text-destructive text-sm">{errorMessage(jobs.error)}</p>
      )}

      <div className="overflow-x-auto rounded-xl border">
        <table className="w-full min-w-[720px] text-sm">
          <thead className="bg-muted/50 text-muted-foreground text-left text-xs">
            <tr>
              <th className="px-3 py-2 font-medium">Role</th>
              <th className="px-3 py-2 font-medium">Company</th>
              <th className="px-3 py-2 font-medium">Location</th>
              <th className="px-3 py-2 font-medium">Type</th>
              <th className="px-3 py-2 font-medium">Age</th>
              <th className="px-3 py-2 font-medium">Source</th>
            </tr>
          </thead>
          <tbody>
            {jobs.data?.items.map((job) => (
              <tr key={job.id} className="border-t align-top">
                <td className="px-3 py-2 font-medium">
                  {job.url ? (
                    <a
                      href={job.url}
                      target="_blank"
                      rel="noreferrer"
                      className="inline-flex items-start gap-1 hover:underline"
                    >
                      {job.title}
                      <ExternalLink className="text-muted-foreground mt-0.5 size-3 shrink-0" />
                    </a>
                  ) : (
                    job.title
                  )}
                </td>
                <td className="px-3 py-2">{job.company.name}</td>
                <td className="px-3 py-2">
                  <span className="text-muted-foreground">
                    {job.location ?? "Not stated"}
                  </span>
                  {job.remote && (
                    <Badge variant="secondary" className="ml-1.5">
                      Remote
                    </Badge>
                  )}
                </td>
                <td className="px-3 py-2">
                  {job.employment_type ? TYPE_LABELS[job.employment_type] : "—"}
                </td>
                <td
                  className="text-muted-foreground px-3 py-2 whitespace-nowrap"
                  title={
                    job.posted_at
                      ? `Posted ${new Date(job.posted_at).toLocaleDateString()}`
                      : `First seen ${new Date(job.first_seen_at).toLocaleDateString()}`
                  }
                >
                  {age(job.age_days)}
                </td>
                <td className="text-muted-foreground px-3 py-2">
                  {SOURCE_LABELS[job.source] ?? job.source}
                </td>
              </tr>
            ))}
            {jobs.data && jobs.data.items.length === 0 && (
              <tr>
                <td
                  colSpan={6}
                  className="text-muted-foreground px-3 py-10 text-center"
                >
                  No jobs match these filters yet.
                </td>
              </tr>
            )}
            {jobs.isPending && (
              <tr>
                <td
                  colSpan={6}
                  className="text-muted-foreground px-3 py-10 text-center"
                >
                  Loading…
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {total > 0 && (
        <div className="text-muted-foreground flex items-center justify-between text-sm">
          <span>
            {filters.offset + 1}–{Math.min(filters.offset + PAGE_SIZE, total)}{" "}
            of {total}
          </span>
          <div className="flex gap-2">
            <Button
              variant="outline"
              size="sm"
              disabled={filters.offset === 0}
              onClick={() =>
                setFilters((f) => ({
                  ...f,
                  offset: Math.max(0, f.offset - PAGE_SIZE),
                }))
              }
            >
              Previous
            </Button>
            <Button
              variant="outline"
              size="sm"
              disabled={filters.offset + PAGE_SIZE >= total}
              onClick={() =>
                setFilters((f) => ({ ...f, offset: f.offset + PAGE_SIZE }))
              }
            >
              Next
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}

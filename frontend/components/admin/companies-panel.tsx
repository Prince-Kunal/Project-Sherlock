"use client";

import { useState } from "react";

import { Cell, DataTable } from "@/components/admin/table";
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
import {
  useAddRegistryCompany,
  usePollNow,
  useRegistryCompanies,
} from "@/lib/queries";
import type { AtsType, RegistryCompanyIn, SizeHint } from "@/lib/types";

const ATS: { value: AtsType; label: string }[] = [
  { value: "greenhouse", label: "Greenhouse" },
  { value: "lever", label: "Lever" },
  { value: "ashby", label: "Ashby" },
  { value: "none", label: "No job board" },
];
const SIZES: { value: SizeHint; label: string }[] = [
  { value: "unknown", label: "Unknown" },
  { value: "startup", label: "Startup" },
  { value: "mid", label: "Mid-size" },
  { value: "large", label: "Large" },
];
const EMPTY: RegistryCompanyIn = {
  name: "",
  domain: null,
  ats_type: "greenhouse",
  ats_token: null,
  size_hint: "unknown",
};

const selectClass =
  "border-input bg-surface dark:bg-input/30 h-9 rounded-[10px] border px-2.5 text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50";

function AddCompanyForm() {
  const add = useAddRegistryCompany();
  const [c, setC] = useState(EMPTY);
  const set = (patch: Partial<RegistryCompanyIn>) =>
    setC((cur) => ({ ...cur, ...patch }));

  return (
    <form
      className="flex flex-col gap-3"
      onSubmit={(e) => {
        e.preventDefault();
        add.mutate(c, { onSuccess: () => setC(EMPTY) });
      }}
    >
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
        <Label className="flex flex-col items-stretch gap-1 font-normal">
          <span className="text-sm">Name</span>
          <Input
            required
            value={c.name}
            onChange={(e) => set({ name: e.target.value })}
          />
        </Label>
        <Label className="flex flex-col items-stretch gap-1 font-normal">
          <span className="text-sm">Website</span>
          <Input
            placeholder="example.com"
            value={c.domain ?? ""}
            onChange={(e) => set({ domain: e.target.value || null })}
          />
        </Label>
        <Label className="flex flex-col items-stretch gap-1 font-normal">
          <span className="text-sm">Job board</span>
          <select
            className={selectClass}
            value={c.ats_type}
            onChange={(e) => set({ ats_type: e.target.value as AtsType })}
          >
            {ATS.map((a) => (
              <option key={a.value} value={a.value}>
                {a.label}
              </option>
            ))}
          </select>
        </Label>
        <Label className="flex flex-col items-stretch gap-1 font-normal">
          <span className="text-sm">Board token</span>
          <Input
            placeholder="e.g. stripe"
            disabled={c.ats_type === "none"}
            required={c.ats_type !== "none"}
            value={c.ats_token ?? ""}
            onChange={(e) => set({ ats_token: e.target.value || null })}
          />
        </Label>
        <Label className="flex flex-col items-stretch gap-1 font-normal">
          <span className="text-sm">Size</span>
          <select
            className={selectClass}
            value={c.size_hint}
            onChange={(e) => set({ size_hint: e.target.value as SizeHint })}
          >
            {SIZES.map((s) => (
              <option key={s.value} value={s.value}>
                {s.label}
              </option>
            ))}
          </select>
        </Label>
      </div>
      <div className="flex flex-wrap items-center gap-3">
        <Button type="submit" disabled={add.isPending}>
          {add.isPending ? "Checking the board…" : "Add company"}
        </Button>
        {add.isError && (
          <span className="text-destructive text-sm">
            {errorMessage(add.error)}
          </span>
        )}
        {add.data && (
          <span className="text-muted-foreground text-sm">
            Added {add.data.name}
            {add.data.jobs_on_board !== null &&
              ` (${add.data.jobs_on_board} jobs on its board)`}
            .
          </span>
        )}
      </div>
    </form>
  );
}

/** The company registry whose job boards are polled every 6 hours. */
export function CompaniesPanel() {
  const companies = useRegistryCompanies();
  const poll = usePollNow();
  const [q, setQ] = useState("");
  const needle = q.trim().toLowerCase();
  const rows = (companies.data ?? []).filter(
    (c) =>
      !needle ||
      c.name.toLowerCase().includes(needle) ||
      (c.domain ?? "").includes(needle),
  );

  return (
    <div className="flex flex-col gap-6">
      <Card>
        <CardHeader>
          <CardTitle>Add a company</CardTitle>
          <CardDescription>
            A Greenhouse, Lever or Ashby board is checked with one request
            before it&apos;s saved. Its jobs arrive with the next poll.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <AddCompanyForm />
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle>Registry</CardTitle>
          <CardDescription>
            {companies.data
              ? `${companies.data.length} companies. Boards are polled every 6 hours.`
              : "Loading…"}
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
            <Input
              type="search"
              aria-label="Search companies"
              placeholder="Search by name or website"
              value={q}
              onChange={(e) => setQ(e.target.value)}
            />
            <Button
              variant="outline"
              disabled={poll.isPending}
              onClick={() => poll.mutate()}
            >
              {poll.isSuccess ? "Poll queued" : "Poll all boards now"}
            </Button>
          </div>
          {companies.isError && (
            <p className="text-destructive text-sm">
              {errorMessage(companies.error)}
            </p>
          )}
          {rows.length > 0 && (
            <DataTable
              head={["Company", "Board", "Size", "Active jobs", "Last polled"]}
            >
              {rows.map((c) => (
                <tr key={c.id}>
                  <Cell>
                    <div className="font-medium">{c.name}</div>
                    {c.domain && (
                      <div className="text-muted-foreground text-xs">
                        {c.domain}
                      </div>
                    )}
                  </Cell>
                  <Cell>
                    {c.ats_type === "none"
                      ? "—"
                      : `${c.ats_type} · ${c.ats_token}`}
                  </Cell>
                  <Cell>{c.size_hint}</Cell>
                  <Cell className="tabular-nums">{c.active_jobs}</Cell>
                  <Cell className="text-muted-foreground whitespace-nowrap">
                    {c.last_polled_at
                      ? new Date(c.last_polled_at).toLocaleString()
                      : "never"}
                  </Cell>
                </tr>
              ))}
            </DataTable>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

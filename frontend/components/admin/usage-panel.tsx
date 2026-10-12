"use client";

import { useState } from "react";

import { Cell, DataTable } from "@/components/admin/table";
import { Badge } from "@/components/ui/badge";
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
import { useAdminUsage } from "@/lib/queries";

const usd = (value: string) => `$${Number(value).toFixed(2)}`;

/** Per-user usage and estimated costs for one month, from the usage ledger. */
export function UsagePanel() {
  const [month, setMonth] = useState<string | null>(null);
  const usage = useAdminUsage(month);
  const report = usage.data;

  return (
    <div className="flex flex-col gap-6">
      <Card>
        <CardHeader>
          <CardTitle>Usage by person</CardTitle>
          <CardDescription>
            LLM requests and contact lookups per person this month, with
            estimated costs (zero on Gemini&apos;s free tier). Each person may
            use {report?.contact_lookups_limit ?? "…"} lookups and{" "}
            {report ? usd(report.llm_usd_limit) : "…"} of AI a month.
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          <Label className="flex w-48 flex-col items-stretch gap-1 font-normal">
            <span className="text-sm">Month</span>
            <Input
              type="month"
              value={month ?? report?.month ?? ""}
              onChange={(e) => setMonth(e.target.value || null)}
            />
          </Label>
          {usage.isError && (
            <p className="text-destructive text-sm">
              {errorMessage(usage.error)}
            </p>
          )}
          {report && (
            <DataTable
              head={[
                "Person",
                "LLM requests",
                "AI cost",
                "Lookups",
                "Verifications",
                "Sent",
                "Total cost",
              ]}
            >
              {report.users.map((u) => (
                <tr key={u.user_id}>
                  <Cell>
                    <div className="flex flex-wrap items-center gap-1.5">
                      <span className="font-medium">{u.name || u.email}</span>
                      {u.is_admin && <Badge variant="secondary">admin</Badge>}
                      {!u.onboarded && (
                        <Badge variant="outline">setting up</Badge>
                      )}
                      {!u.is_active && (
                        <Badge variant="destructive">inactive</Badge>
                      )}
                      {u.quota_exceeded.length > 0 && (
                        <Badge variant="destructive">over quota</Badge>
                      )}
                    </div>
                    <div className="text-muted-foreground text-xs">
                      {u.email}
                    </div>
                  </Cell>
                  <Cell className="tabular-nums">{u.llm_calls}</Cell>
                  <Cell className="tabular-nums">{usd(u.llm_usd)}</Cell>
                  <Cell className="tabular-nums">
                    {u.contact_lookups} / {report.contact_lookups_limit}
                  </Cell>
                  <Cell className="tabular-nums">
                    {u.contact_verifications}
                  </Cell>
                  <Cell className="tabular-nums">{u.sent}</Cell>
                  <Cell className="tabular-nums">{usd(u.est_cost_usd)}</Cell>
                </tr>
              ))}
            </DataTable>
          )}
        </CardContent>
      </Card>

      {report && report.operations.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>By operation</CardTitle>
            <CardDescription>
              Everyone together, {report.month}.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <DataTable head={["Provider", "Operation", "Units", "Cost"]}>
              {report.operations.map((op) => (
                <tr key={`${op.provider}:${op.operation}`}>
                  <Cell>{op.provider}</Cell>
                  <Cell className="font-mono text-xs">{op.operation}</Cell>
                  <Cell className="tabular-nums">{op.units}</Cell>
                  <Cell className="tabular-nums">{usd(op.est_cost_usd)}</Cell>
                </tr>
              ))}
            </DataTable>
          </CardContent>
        </Card>
      )}
    </div>
  );
}

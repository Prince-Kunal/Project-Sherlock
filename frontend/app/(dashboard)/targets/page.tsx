"use client";

import { Pencil, Plus } from "lucide-react";
import { useState } from "react";

import { PageHeader } from "@/components/page-header";
import { CompanyMatches } from "@/components/targets/company-matches";
import { TargetForm } from "@/components/targets/target-form";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { errorMessage } from "@/lib/api";
import { useTargets } from "@/lib/queries";
import type { ProspectTarget } from "@/lib/types";

function summary(t: ProspectTarget): string {
  const parts = [
    t.industries.length ? t.industries.join(", ") : "any industry",
    t.locations.length ? t.locations.join(", ") : "anywhere",
    t.company_sizes.length ? t.company_sizes.join("/") : "any size",
  ];
  return parts.join(" · ");
}

export default function TargetsPage() {
  const targets = useTargets();
  // null: no form open; "new": creating; otherwise the id being edited.
  const [editing, setEditing] = useState<string | null>(null);
  const list = targets.data ?? [];
  const showForm = editing !== null || (targets.isSuccess && !list.length);

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Targets"
        description="Open outreach: reach people at companies you'd like to work at, even with no job posted. The email never claims there's an opening."
        actions={
          !showForm && (
            <Button onClick={() => setEditing("new")}>
              <Plus /> New target
            </Button>
          )
        }
      />

      {targets.isError && (
        <p className="text-destructive text-sm">
          {errorMessage(targets.error)}
        </p>
      )}

      {showForm && (
        <Card>
          <CardHeader>
            <CardTitle>
              {editing && editing !== "new" ? "Edit target" : "New target"}
            </CardTitle>
            <CardDescription>
              Who and where you want to reach. Companies come from the YC
              directory and the job feed, plus any you add yourself.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <TargetForm
              key={editing ?? "new"}
              target={list.find((t) => t.id === editing) ?? null}
              onDone={() => setEditing(null)}
            />
          </CardContent>
        </Card>
      )}

      {list.length > 0 && (
        <ul className="grid gap-2 sm:grid-cols-2">
          {list.map((t) => (
            <li
              key={t.id}
              className="bg-card ring-foreground/[0.07] shadow-soft flex items-start justify-between gap-3 rounded-2xl p-4 ring-1"
            >
              <div className="min-w-0">
                <p className="font-medium">
                  {t.name}
                  {!t.is_active && (
                    <Badge variant="secondary" className="ml-2 align-middle">
                      Paused
                    </Badge>
                  )}
                </p>
                <p className="text-muted-foreground text-sm">{summary(t)}</p>
                {t.contact_titles.length > 0 && (
                  <p className="text-muted-foreground text-xs">
                    Emails: {t.contact_titles.join(", ")}
                  </p>
                )}
              </div>
              <Button
                variant="ghost"
                size="sm"
                onClick={() => setEditing(t.id)}
              >
                <Pencil /> Edit
              </Button>
            </li>
          ))}
        </ul>
      )}

      {list.length > 0 && (
        <section className="flex flex-col gap-3">
          <h2 className="text-lg font-semibold tracking-tight">
            Matching companies
          </h2>
          <CompanyMatches targets={list} />
        </section>
      )}
    </div>
  );
}

"use client";

import { EmptyState } from "@/components/empty-state";
import {
  ArrowRight,
  ChevronDown,
  ExternalLink,
  EyeOff,
  ListPlus,
  RefreshCw,
  RotateCcw,
  Sparkles,
} from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ListSkeleton } from "@/components/ui/skeleton";
import { Label } from "@/components/ui/label";
import { errorMessage } from "@/lib/api";
import { CANON } from "@/lib/canon";
import { selectClass } from "@/lib/jobs";
import { scoreClass } from "@/lib/score";
import {
  useCompanyMatchAction,
  useCompanyMatches,
  useDraftCompanyNow,
  useFindCompanies,
} from "@/lib/queries";
import type {
  CompanyMatch,
  CompanyMatchFilters,
  ProspectTarget,
} from "@/lib/types";
import { WarmPathBadge } from "@/components/warm-path";

const PAGE_SIZE = 30;

const STATUS_OPTIONS: {
  value: CompanyMatchFilters["status"];
  label: string;
}[] = [
  { value: "active", label: "New, queued and contacted" },
  { value: "queued", label: "Queued" },
  { value: "contacted", label: "Contacted" },
  { value: "hidden", label: "Hidden" },
];

const SIZE_LABELS: Record<string, string> = {
  startup: "Startup",
  mid: "Mid-size",
  large: "Large",
  unknown: "Size unknown",
};

export function CompanyMatches({ targets }: { targets: ProspectTarget[] }) {
  const [filters, setFilters] = useState<CompanyMatchFilters>({
    status: "active",
    limit: PAGE_SIZE,
    offset: 0,
  });
  const matches = useCompanyMatches(filters);
  const find = useFindCompanies();
  const update = (patch: Partial<CompanyMatchFilters>) =>
    setFilters((f) => ({ ...f, ...patch, offset: 0 }));
  const data = matches.data;
  const total = data?.total ?? 0;
  const anyActive = targets.some((t) => t.is_active);

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div className="flex flex-wrap items-end gap-3">
          <Label className="flex flex-col items-start gap-1 font-normal">
            <span className="text-muted-foreground text-xs">Show</span>
            <select
              aria-label="Company match status"
              className={selectClass}
              value={filters.status}
              onChange={(e) =>
                update({
                  status: e.target.value as CompanyMatchFilters["status"],
                })
              }
            >
              {STATUS_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </select>
          </Label>
          <Label className="flex flex-col items-start gap-1 font-normal">
            <span className="text-muted-foreground text-xs">Fit score</span>
            <select
              aria-label="Minimum fit score"
              className={selectClass}
              value={filters.min_score ?? ""}
              onChange={(e) =>
                update({
                  min_score: e.target.value
                    ? Number(e.target.value)
                    : undefined,
                })
              }
            >
              <option value="">Your minimum</option>
              {[85, 70, 50, 0].map((s) => (
                <option key={s} value={s}>
                  {s === 0 ? "Any score" : `${s} or more`}
                </option>
              ))}
            </select>
          </Label>
          {targets.length > 1 && (
            <Label className="flex flex-col items-start gap-1 font-normal">
              <span className="text-muted-foreground text-xs">Target</span>
              <select
                aria-label="Target"
                className={selectClass}
                value={filters.target_id ?? ""}
                onChange={(e) =>
                  update({ target_id: e.target.value || undefined })
                }
              >
                <option value="">All targets</option>
                {targets.map((t) => (
                  <option key={t.id} value={t.id}>
                    {t.name}
                  </option>
                ))}
              </select>
            </Label>
          )}
        </div>
        <Button
          variant="outline"
          size="sm"
          disabled={!anyActive || find.isPending || find.isSuccess}
          onClick={() => find.mutate()}
          title="Find and score companies for your active targets now instead of tonight"
        >
          <RefreshCw />
          {find.isSuccess
            ? find.data.queued
              ? "Search queued"
              : "Already running"
            : "Find companies now"}
        </Button>
      </div>

      {find.isSuccess && find.data.queued && (
        <p className="text-muted-foreground text-sm">
          Searching runs in the background: new companies, their websites, then
          scoring with your Gemini key. Give it a few minutes, then reload.
        </p>
      )}
      {(find.isError || matches.isError) && (
        <p className="text-destructive text-sm">
          {errorMessage(find.error ?? matches.error)}
        </p>
      )}

      <ul className="flex flex-col gap-2">
        {data?.items.map((match) => (
          <CompanyRow key={match.id} match={match} />
        ))}
      </ul>

      {data && data.items.length === 0 && (
        <EmptyState
          title={
            filters.status !== "active"
              ? "Nothing here."
              : anyActive
                ? `No companies at ${filters.min_score ?? data.min_score}+ yet.`
                : "No active target."
          }
          quote={filters.status === "active" ? CANON.business : undefined}
        >
          {filters.status === "active" && (
            <p>
              {anyActive
                ? "Companies are found and scored every night, a few a day on the free tier. Try a lower fit score, or “Find companies now”."
                : "Turn a target on above and Sherlock will start finding companies for it."}
            </p>
          )}
        </EmptyState>
      )}
      {matches.isPending && <ListSkeleton />}

      {total > PAGE_SIZE && (
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

function CompanyRow({ match }: { match: CompanyMatch }) {
  const [open, setOpen] = useState(false);
  const action = useCompanyMatchAction();
  const draft = useDraftCompanyNow();
  const { company } = match;
  const status = draft.data?.status ?? match.outreach?.status;
  const place = company.hq_location;

  return (
    <li className="bg-card ring-foreground/[0.07] shadow-soft hover:shadow-lift rounded-2xl p-4 ring-1 transition-shadow duration-300 sm:p-5">
      <div className="flex gap-3">
        <div
          className={`size-11 text-base ${scoreClass(match.score)}`}
          title="Fit score out of 100"
        >
          {match.score}
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-start justify-between gap-2">
            <div className="min-w-0">
              {company.domain ? (
                <a
                  href={`https://${company.domain}`}
                  target="_blank"
                  rel="noreferrer"
                  className="inline-flex items-start gap-1 font-medium hover:underline"
                >
                  {company.name}
                  <ExternalLink className="text-muted-foreground mt-1 size-3 shrink-0" />
                </a>
              ) : (
                <span className="font-medium">{company.name}</span>
              )}
              {match.status === "queued" && (
                <Badge className="ml-2 align-middle">Queued</Badge>
              )}
              {match.status === "contacted" && (
                <Badge variant="secondary" className="ml-2 align-middle">
                  In pipeline
                </Badge>
              )}
              <p className="text-muted-foreground text-sm">
                {[
                  place,
                  SIZE_LABELS[company.size_hint] +
                    (company.employee_count
                      ? ` (${company.employee_count})`
                      : ""),
                  match.target_name && `for “${match.target_name}”`,
                ]
                  .filter(Boolean)
                  .join(" · ")}
              </p>
            </div>
            <div className="flex shrink-0 items-center gap-1">
              {match.status === "hidden" ? (
                <Button
                  variant="ghost"
                  size="sm"
                  disabled={action.isPending}
                  onClick={() =>
                    action.mutate({ id: match.id, action: "restore" })
                  }
                >
                  <RotateCcw /> Restore
                </Button>
              ) : match.status !== "contacted" ? (
                <>
                  <Button
                    variant="ghost"
                    size="sm"
                    disabled={action.isPending}
                    aria-pressed={match.status === "queued"}
                    title="Draft this one first in the next daily batch"
                    onClick={() =>
                      action.mutate({
                        id: match.id,
                        action: match.status === "queued" ? "restore" : "queue",
                      })
                    }
                  >
                    <ListPlus />
                    {match.status === "queued" ? "Queued" : "Queue"}
                  </Button>
                  <Button
                    variant="ghost"
                    size="sm"
                    disabled={action.isPending}
                    onClick={() =>
                      action.mutate({ id: match.id, action: "hide" })
                    }
                  >
                    <EyeOff /> Hide
                  </Button>
                </>
              ) : null}
            </div>
          </div>

          {match.angle && <p className="mt-2 text-sm">{match.angle}</p>}
          {match.warm_path && (
            <div className="mt-2">
              <WarmPathBadge path={match.warm_path} />
            </div>
          )}
          {company.industry_tags.length > 0 && (
            <div className="mt-2 flex flex-wrap gap-1">
              {company.industry_tags.slice(0, 6).map((tag) => (
                <Badge key={tag} variant="outline">
                  {tag}
                </Badge>
              ))}
            </div>
          )}

          <button
            type="button"
            className="text-muted-foreground hover:text-foreground mt-2 inline-flex items-center gap-1 text-xs"
            aria-expanded={open}
            onClick={() => setOpen((o) => !o)}
          >
            <ChevronDown
              className={`size-3.5 transition-transform ${open ? "rotate-180" : ""}`}
            />
            Why this score
          </button>
          {open && (
            <div className="mt-1 flex flex-col gap-2 text-sm">
              <p>{match.reasoning}</p>
              {company.description && (
                <p className="text-muted-foreground">{company.description}</p>
              )}
            </div>
          )}

          {match.status !== "hidden" &&
            (status === "pending_review" ? (
              <Link
                href="/review"
                className="mt-2 inline-flex items-center gap-1 text-sm font-medium underline-offset-4 hover:underline"
              >
                Draft ready in the review queue{" "}
                <ArrowRight className="size-3.5" />
              </Link>
            ) : !status || status === "drafting" || status === "failed" ? (
              <div className="mt-2">
                <Button
                  size="sm"
                  disabled={draft.isPending}
                  onClick={() => draft.mutate(match.id)}
                  title="Find a contact, tailor your resume and write the email now"
                >
                  <Sparkles />
                  {draft.isPending
                    ? "Drafting… (about 30 s)"
                    : status === "failed"
                      ? "Try drafting again"
                      : "Draft now"}
                </Button>
                {status === "failed" && match.outreach?.failure_message && (
                  <p className="text-muted-foreground mt-1 text-sm">
                    Last try: {match.outreach.failure_message}
                  </p>
                )}
              </div>
            ) : null)}
          {(action.isError || draft.isError) && (
            <p className="text-destructive mt-1 text-sm">
              {errorMessage(action.error ?? draft.error)}
            </p>
          )}
        </div>
      </div>
    </li>
  );
}

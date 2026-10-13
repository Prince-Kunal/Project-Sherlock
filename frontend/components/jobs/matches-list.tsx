"use client";

import {
  Ban,
  ChevronDown,
  ExternalLink,
  EyeOff,
  RefreshCw,
  RotateCcw,
  Star,
} from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { ContactPanel } from "@/components/jobs/contact-panel";
import { DraftNowButton } from "@/components/jobs/draft-now";
import { EmptyState } from "@/components/empty-state";
import { TailorPreviewButton } from "@/components/jobs/tailor-preview";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ListSkeleton } from "@/components/ui/skeleton";
import { Label } from "@/components/ui/label";
import { errorMessage } from "@/lib/api";
import { CANON } from "@/lib/canon";
import { age, selectClass, TYPE_LABELS } from "@/lib/jobs";
import {
  useBlockCompany,
  useMatchAction,
  useMatches,
  useRefreshMatches,
} from "@/lib/queries";
import type { Match, MatchFilters } from "@/lib/types";
import { scoreClass } from "@/lib/score";
import { WarmPathBadge } from "@/components/warm-path";

const PAGE_SIZE = 30;

const STATUS_OPTIONS: { value: MatchFilters["status"]; label: string }[] = [
  { value: "active", label: "New and shortlisted" },
  { value: "shortlisted", label: "Shortlisted" },
  { value: "hidden", label: "Hidden" },
  { value: "expired", label: "Expired" },
];

export function MatchesList() {
  const [filters, setFilters] = useState<MatchFilters>({
    status: "active",
    limit: PAGE_SIZE,
    offset: 0,
  });
  const matches = useMatches(filters);
  const refresh = useRefreshMatches();
  const update = (patch: Partial<MatchFilters>) =>
    setFilters((f) => ({ ...f, ...patch, offset: 0 }));

  const data = matches.data;
  const total = data?.total ?? 0;
  const userMin = data?.min_score ?? 70;

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div className="flex flex-wrap items-end gap-3">
          <Label className="flex flex-col items-start gap-1 font-normal">
            <span className="text-muted-foreground text-xs">Show</span>
            <select
              aria-label="Match status"
              className={selectClass}
              value={filters.status}
              onChange={(e) =>
                update({ status: e.target.value as MatchFilters["status"] })
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
        </div>
        <div className="flex items-center gap-3">
          {data && (
            <span
              className="text-muted-foreground text-xs"
              title="Scoring uses your Gemini key's free fast-model quota. New jobs left over are scored on the next run."
            >
              Scoring: {data.scoring.calls_last_24h} of{" "}
              {data.scoring.daily_limit} requests used today
            </span>
          )}
          <Button
            variant="outline"
            size="sm"
            disabled={refresh.isPending || refresh.isSuccess}
            onClick={() => refresh.mutate()}
            title="Score new jobs now instead of after the next poll"
          >
            <RefreshCw />
            {refresh.isSuccess
              ? refresh.data.queued
                ? "Scoring queued"
                : "Already running"
              : "Score new jobs"}
          </Button>
        </div>
      </div>

      {refresh.isSuccess && refresh.data.queued && (
        <p className="text-muted-foreground text-sm">
          Scoring runs in the background and takes a minute or two; reload this
          page to see the results.
        </p>
      )}
      {refresh.isError && (
        <p className="text-destructive text-sm">
          {errorMessage(refresh.error)}
        </p>
      )}

      {data && !data.scoring.llm_key_configured && (
        <Alert>
          <AlertTitle>Add your Gemini key to score jobs</AlertTitle>
          <AlertDescription>
            Matching uses your own free Gemini key.{" "}
            <Link href="/settings" className="underline underline-offset-4">
              Add it in Settings
            </Link>
            , then click “Score new jobs”.
          </AlertDescription>
        </Alert>
      )}

      {matches.isError && (
        <p className="text-destructive text-sm">
          {errorMessage(matches.error)}
        </p>
      )}

      <ul className="flex flex-col gap-2">
        {data?.items.map((match) => (
          <MatchRow key={match.id} match={match} />
        ))}
      </ul>

      {data && data.items.length === 0 && (
        <EmptyState
          title={
            filters.status === "active"
              ? `No matches at ${filters.min_score ?? userMin}+ yet.`
              : "Nothing here."
          }
          quote={filters.status === "active" ? CANON.data : undefined}
        >
          {filters.status === "active" && (
            <p>
              Sherlock scores new jobs after each poll (every 6 hours), up to{" "}
              {data.scoring.daily_limit} requests a day. Try a lower fit score,
              or browse “All jobs”.
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

function MatchRow({ match }: { match: Match }) {
  const [open, setOpen] = useState(false);
  const [confirmBlock, setConfirmBlock] = useState(false);
  const action = useMatchAction();
  const block = useBlockCompany();
  const { job } = match;
  const busy = action.isPending || block.isPending;
  const editable = ["new", "shortlisted", "hidden"].includes(match.status);

  return (
    <li className="bg-card ring-foreground/[0.07] shadow-soft hover:shadow-lift rounded-2xl p-4 ring-1 transition-shadow duration-300 sm:p-5">
      <div className="flex gap-3">
        <div
          className={`size-11 text-base ${scoreClass(match.fit_score)}`}
          title={
            match.fit_score === null ? "Not scored" : "Fit score out of 100"
          }
        >
          {match.fit_score ?? "–"}
        </div>

        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-start justify-between gap-2">
            <div className="min-w-0">
              {job.url ? (
                <a
                  href={job.url}
                  target="_blank"
                  rel="noreferrer"
                  className="inline-flex items-start gap-1 font-medium hover:underline"
                >
                  {job.title}
                  <ExternalLink className="text-muted-foreground mt-1 size-3 shrink-0" />
                </a>
              ) : (
                <span className="font-medium">{job.title}</span>
              )}
              {match.status === "in_pipeline" && (
                <Badge variant="secondary" className="ml-2 align-middle">
                  In pipeline
                </Badge>
              )}
              <p className="text-muted-foreground text-sm">
                {job.company.name} · {job.location ?? "Location not stated"}
                {job.remote && " · Remote"} · {age(job.age_days)}
                {job.employment_type &&
                  ` · ${TYPE_LABELS[job.employment_type]}`}
              </p>
              <WarmPathBadge path={match.warm_path} />
            </div>

            {editable && (
              <div className="flex shrink-0 items-center gap-1">
                {match.status === "hidden" ? (
                  <Button
                    variant="ghost"
                    size="sm"
                    disabled={busy}
                    onClick={() =>
                      action.mutate({ id: match.id, action: "restore" })
                    }
                  >
                    <RotateCcw /> Restore
                  </Button>
                ) : (
                  <>
                    <Button
                      variant="ghost"
                      size="sm"
                      disabled={busy}
                      aria-pressed={match.status === "shortlisted"}
                      onClick={() =>
                        action.mutate({
                          id: match.id,
                          action:
                            match.status === "shortlisted"
                              ? "restore"
                              : "shortlist",
                        })
                      }
                    >
                      <Star
                        className={
                          match.status === "shortlisted"
                            ? "fill-amber-400 text-amber-500"
                            : undefined
                        }
                      />
                      {match.status === "shortlisted"
                        ? "Shortlisted"
                        : "Shortlist"}
                    </Button>
                    <Button
                      variant="ghost"
                      size="sm"
                      disabled={busy}
                      onClick={() =>
                        action.mutate({ id: match.id, action: "hide" })
                      }
                    >
                      <EyeOff /> Hide
                    </Button>
                  </>
                )}
                {confirmBlock ? (
                  <>
                    <Button
                      variant="destructive"
                      size="sm"
                      disabled={busy}
                      onClick={() => block.mutate(job.company.id)}
                    >
                      Block {job.company.name}
                    </Button>
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => setConfirmBlock(false)}
                    >
                      Cancel
                    </Button>
                  </>
                ) : (
                  <Button
                    variant="ghost"
                    size="sm"
                    disabled={busy}
                    title={`Never show jobs from ${job.company.name}`}
                    onClick={() => setConfirmBlock(true)}
                  >
                    <Ban /> Block
                  </Button>
                )}
              </div>
            )}
          </div>

          {(match.matched_skills.length > 0 ||
            match.missing_skills.length > 0) && (
            <div className="mt-2 flex flex-wrap items-center gap-1.5">
              {match.matched_skills.map((s) => (
                <Badge key={`m-${s}`} variant="secondary">
                  {s}
                </Badge>
              ))}
              {match.missing_skills.length > 0 && (
                <span className="text-muted-foreground ml-1 text-xs">
                  Missing:
                </span>
              )}
              {match.missing_skills.map((s) => (
                <Badge
                  key={`x-${s}`}
                  variant="outline"
                  className="text-muted-foreground border-dashed"
                >
                  {s}
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
          {open && <p className="mt-1 text-sm">{match.reasoning}</p>}
          {(editable || match.status === "in_pipeline") &&
            match.fit_score !== null && (
              <>
                <ContactPanel match={match} />
                <div className="flex flex-wrap items-start gap-x-2">
                  <DraftNowButton match={match} />
                  <TailorPreviewButton matchId={match.id} />
                </div>
              </>
            )}
          {(action.isError || block.isError) && (
            <p className="text-destructive mt-1 text-sm">
              {errorMessage(action.error ?? block.error)}
            </p>
          )}
        </div>
      </div>
    </li>
  );
}

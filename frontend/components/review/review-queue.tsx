"use client";

import { RotateCcw, Sparkles } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";

import { FAILURE_LABELS } from "@/components/jobs/contact-panel";
import { DraftCard } from "@/components/review/draft-card";
import { EmptyState } from "@/components/empty-state";
import { Button } from "@/components/ui/button";
import { ListSkeleton, Skeleton } from "@/components/ui/skeleton";
import { errorMessage } from "@/lib/api";
import { CANON } from "@/lib/canon";
import {
  useBuildDrafts,
  useOutreachDetail,
  useOutreachList,
  useReviewAction,
  useReviewStats,
} from "@/lib/queries";
import type { OutreachListItem, ReviewStats } from "@/lib/types";
import { scoreClass } from "@/lib/score";
import { cn } from "@/lib/utils";

const MORE_FAILURE_LABELS: Record<string, string> = {
  validation_failed: "The tailored resume failed validation",
  page_overflow: "The resume didn't fit on one page",
  ats_check_failed: "The resume failed the ATS check",
  draft_validation_failed: "The email failed validation twice",
  llm_output_invalid: "The AI returned an unusable answer",
  no_resume: "Upload your resume first",
  no_company_context: "Nothing to quote from the company's site yet",
  missing_inputs: "Its job or company match no longer exists",
};

function failureLabel(reason: string | null): string {
  return (
    FAILURE_LABELS[reason ?? ""] ??
    MORE_FAILURE_LABELS[reason ?? ""] ??
    "Drafting failed"
  );
}

function isTyping(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  return (
    target.isContentEditable ||
    ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName)
  );
}

export function ReviewQueue() {
  const stats = useReviewStats();
  const pending = useOutreachList(["pending_review"]);
  const items = pending.data?.items ?? [];
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const current = items.find((i) => i.id === selectedId) ?? items[0] ?? null;
  const index = current ? items.indexOf(current) : -1;
  const detail = useOutreachDetail(current?.id ?? null);
  const keyAction = useReviewAction();

  // After approve/skip the item leaves the list: move to its neighbour.
  const next = () =>
    setSelectedId(items[index + 1]?.id ?? items[index - 1]?.id ?? null);

  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if (event.metaKey || event.ctrlKey || event.altKey) return;
      if (isTyping(event.target)) return;
      if (event.key === "j" && index < items.length - 1) {
        setSelectedId(items[index + 1].id);
      } else if (event.key === "k" && index > 0) {
        setSelectedId(items[index - 1].id);
      } else if (
        (event.key === "a" || event.key === "s") &&
        current &&
        !keyAction.isPending
      ) {
        keyAction.mutate(
          { id: current.id, action: event.key === "a" ? "approve" : "skip" },
          { onSuccess: next },
        );
      } else {
        return;
      }
      event.preventDefault();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  return (
    <div className="flex flex-col gap-4">
      {stats.data && <StatCards stats={stats.data} />}

      {pending.isError && (
        <p className="text-destructive text-sm">
          {errorMessage(pending.error)}
        </p>
      )}
      {pending.isPending && <ListSkeleton rows={3} label="Loading drafts" />}

      {pending.data && items.length === 0 && <EmptyQueue />}

      {items.length > 0 && (
        <div className="grid items-start gap-5 lg:grid-cols-[17rem_1fr]">
          <nav aria-label="Drafts waiting for review">
            <ul className="flex gap-2 overflow-x-auto pb-1 lg:flex-col lg:overflow-visible">
              {items.map((item) => (
                <QueueItem
                  key={item.id}
                  item={item}
                  active={item.id === current?.id}
                  onSelect={() => setSelectedId(item.id)}
                />
              ))}
            </ul>
          </nav>
          <div className="min-w-0">
            {keyAction.isError && (
              <p className="text-destructive mb-2 text-sm">
                {errorMessage(keyAction.error)}
              </p>
            )}
            {detail.data ? (
              <DraftCard
                key={detail.data.id}
                draft={detail.data}
                onDone={next}
              />
            ) : detail.isError ? (
              <p className="text-destructive text-sm">
                {errorMessage(detail.error)}
              </p>
            ) : (
              <div
                role="status"
                aria-label="Loading draft"
                className="bg-card flex flex-col gap-4 rounded-2xl border p-6"
              >
                <Skeleton className="h-6 w-1/2" />
                <Skeleton className="h-4 w-1/3" />
                <Skeleton className="h-40 w-full rounded-xl" />
              </div>
            )}
          </div>
        </div>
      )}

      <NeedsAttention />
    </div>
  );
}

function StatCards({ stats }: { stats: ReviewStats }) {
  const cards = [
    { label: "Waiting for review", value: stats.pending_review },
    {
      label: "New matches",
      value: stats.new_matches + stats.new_company_matches,
      href: stats.new_matches ? "/jobs" : "/targets",
    },
    {
      label: "Sent this week",
      value: stats.sent_this_week,
      note: `cap ${stats.daily_send_cap}/day`,
    },
    { label: "Replies", value: stats.replies },
    { label: "Follow-ups due", value: stats.followups_due },
  ];
  return (
    <dl className="bg-surface ring-foreground/[0.07] shadow-soft [&>*]:border-border grid grid-cols-2 overflow-hidden rounded-2xl ring-1 sm:grid-cols-3 lg:grid-cols-5 [&>*]:border-b [&>*]:sm:border-r lg:[&>*]:border-b-0 lg:[&>*:last-child]:border-r-0">
      {cards.map((card) => {
        const content = (
          <>
            <dt className="text-muted-foreground text-xs">{card.label}</dt>
            <dd className="mt-1 flex items-baseline gap-2">
              <span className="tabular font-mono text-3xl font-semibold tracking-tight">
                {card.value}
              </span>
              {card.note && (
                <span className="text-muted-foreground text-xs">
                  {card.note}
                </span>
              )}
            </dd>
          </>
        );
        return card.href ? (
          <Link
            key={card.label}
            href={card.href}
            className="hover:bg-muted/50 px-5 py-4 transition-colors duration-200"
          >
            {content}
          </Link>
        ) : (
          <div key={card.label} className="px-5 py-4">
            {content}
          </div>
        );
      })}
    </dl>
  );
}

function QueueItem({
  item,
  active,
  onSelect,
}: {
  item: OutreachListItem;
  active: boolean;
  onSelect: () => void;
}) {
  return (
    <li className="shrink-0 lg:shrink">
      <button
        type="button"
        onClick={onSelect}
        aria-current={active ? "true" : undefined}
        className={cn(
          "flex w-56 items-center gap-3 rounded-2xl px-2.5 py-2.5 text-left text-sm transition-[background-color,box-shadow] duration-200 lg:w-full",
          active
            ? "bg-surface shadow-soft ring-brand/45 ring-1"
            : "hover:bg-muted/60",
        )}
      >
        <span className={`size-8 text-xs ${scoreClass(item.fit_score)}`}>
          {item.fit_score ?? "–"}
        </span>
        <span className="min-w-0">
          <span className="block truncate font-medium">
            {item.company.name}
          </span>
          <span className="text-muted-foreground block truncate text-xs">
            {item.campaign_type === "open"
              ? `Open outreach${item.is_followup ? " · follow-up" : ""}`
              : (item.job_title ?? item.subject)}
          </span>
        </span>
      </button>
    </li>
  );
}

function EmptyQueue() {
  const build = useBuildDrafts();
  return (
    <EmptyState
      title="No drafts waiting."
      quote={CANON.clay}
      actions={
        <>
          <Button
            variant="brand"
            disabled={build.isPending || build.isSuccess}
            onClick={() => build.mutate()}
          >
            <Sparkles />
            {build.isSuccess
              ? build.data.queued
                ? "Drafting started"
                : "Already running"
              : "Draft today's batch now"}
          </Button>
          <Link
            href="/jobs"
            className="text-muted-foreground hover:text-foreground px-2 text-sm underline-offset-4 hover:underline"
          >
            Pick a match yourself
          </Link>
        </>
      }
    >
      <p>
        Sherlock drafts your best matches every morning at 07:00, up to your
        daily batch size.
      </p>
      {build.isSuccess && build.data.queued && (
        <p className="mt-2">
          Each draft takes about half a minute: a contact, a tailored resume,
          then the email. Reload in a few minutes.
        </p>
      )}
      {build.isError && (
        <p className="text-destructive mt-2">{errorMessage(build.error)}</p>
      )}
    </EmptyState>
  );
}

/** Failed drafts, with the reason and a retry. */
function NeedsAttention() {
  const failed = useOutreachList(["failed"]);
  const retry = useReviewAction();
  const items = failed.data?.items ?? [];
  if (items.length === 0) return null;

  return (
    <section className="flex flex-col gap-2">
      <h2 className="mt-4 text-lg font-semibold tracking-tight">
        Needs attention
      </h2>
      <ul className="flex flex-col gap-2">
        {items.map((item) => (
          <li
            key={item.id}
            className="bg-card ring-destructive/20 flex flex-wrap items-center justify-between gap-3 rounded-2xl px-4 py-3 text-sm ring-1"
          >
            <div className="min-w-0">
              <p className="font-medium">
                {item.job_title ??
                  (item.campaign_type === "open"
                    ? "Open outreach"
                    : "Outreach")}{" "}
                · {item.company.name}
              </p>
              <p className="text-muted-foreground">
                {failureLabel(item.failure_reason)}
                {item.failure_message && `: ${item.failure_message}`}
              </p>
            </div>
            <div className="flex items-center gap-2">
              {item.failure_reason?.startsWith("contact") ||
              item.failure_reason === "no_contact" ? (
                <Link
                  href="/jobs"
                  className="text-muted-foreground text-xs underline underline-offset-4"
                >
                  Add a contact on the Jobs page
                </Link>
              ) : null}
              <Button
                variant="outline"
                size="sm"
                disabled={retry.isPending}
                onClick={() => retry.mutate({ id: item.id, action: "retry" })}
              >
                <RotateCcw />
                {retry.isPending && retry.variables?.id === item.id
                  ? "Retrying…"
                  : "Retry"}
              </Button>
            </div>
          </li>
        ))}
      </ul>
      {retry.isError && (
        <p className="text-destructive text-sm">{errorMessage(retry.error)}</p>
      )}
    </section>
  );
}

"use client";

import { RotateCcw, Sparkles } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";

import { FAILURE_LABELS } from "@/components/jobs/contact-panel";
import { DraftCard, scoreClass } from "@/components/review/draft-card";
import { Button } from "@/components/ui/button";
import { errorMessage } from "@/lib/api";
import {
  useBuildDrafts,
  useOutreachDetail,
  useOutreachList,
  useReviewAction,
  useReviewStats,
} from "@/lib/queries";
import type { OutreachListItem, ReviewStats } from "@/lib/types";
import { cn } from "@/lib/utils";

const MORE_FAILURE_LABELS: Record<string, string> = {
  validation_failed: "The tailored resume failed validation",
  page_overflow: "The resume didn't fit on one page",
  ats_check_failed: "The resume failed the ATS check",
  draft_validation_failed: "The email failed validation twice",
  llm_output_invalid: "The AI returned an unusable answer",
  no_resume: "Upload your resume first",
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
      {pending.isPending && (
        <p className="text-muted-foreground py-10 text-center text-sm">
          Loading…
        </p>
      )}

      {pending.data && items.length === 0 && <EmptyQueue />}

      {items.length > 0 && (
        <div className="grid items-start gap-4 lg:grid-cols-[17rem_1fr]">
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
              <p className="text-muted-foreground py-10 text-center text-sm">
                Loading draft…
              </p>
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
    { label: "New matches", value: stats.new_matches, href: "/jobs" },
    {
      label: "Sent this week",
      value: stats.sent_this_week,
      note: `cap ${stats.daily_send_cap}/day`,
    },
    { label: "Replies", value: stats.replies },
    { label: "Follow-ups due", value: stats.followups_due },
  ];
  return (
    <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-5">
      {cards.map((card) => {
        const content = (
          <>
            <p className="text-muted-foreground text-xs">{card.label}</p>
            <p className="text-2xl font-semibold tabular-nums">
              {card.value}
              {card.note && (
                <span className="text-muted-foreground ml-1.5 text-xs font-normal">
                  {card.note}
                </span>
              )}
            </p>
          </>
        );
        return card.href ? (
          <Link
            key={card.label}
            href={card.href}
            className="bg-card hover:bg-muted/40 rounded-xl border px-3 py-2 transition-colors"
          >
            {content}
          </Link>
        ) : (
          <div key={card.label} className="bg-card rounded-xl border px-3 py-2">
            {content}
          </div>
        );
      })}
    </div>
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
          "flex w-56 items-center gap-2 rounded-lg border px-2.5 py-2 text-left text-sm transition-colors lg:w-full",
          active ? "border-foreground bg-muted/50" : "hover:bg-muted/30",
        )}
      >
        <span
          className={`flex size-8 shrink-0 items-center justify-center rounded-md text-xs font-semibold tabular-nums ${scoreClass(item.fit_score)}`}
        >
          {item.fit_score ?? "–"}
        </span>
        <span className="min-w-0">
          <span className="block truncate font-medium">
            {item.company.name}
          </span>
          <span className="text-muted-foreground block truncate text-xs">
            {item.job_title ?? item.subject}
          </span>
        </span>
      </button>
    </li>
  );
}

function EmptyQueue() {
  const build = useBuildDrafts();
  return (
    <div className="text-muted-foreground flex flex-col items-center gap-3 rounded-xl border border-dashed px-4 py-10 text-center text-sm">
      <p>
        No drafts waiting. Sherlock drafts your best matches every morning at
        07:00, up to your daily batch size.
      </p>
      <Button
        variant="outline"
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
      {build.isSuccess && build.data.queued && (
        <p>
          Each draft takes about half a minute (finding a contact, tailoring
          your resume, writing the email). Reload in a few minutes.
        </p>
      )}
      {build.isError && (
        <p className="text-destructive">{errorMessage(build.error)}</p>
      )}
      <p>
        Or pick a match on the{" "}
        <Link href="/jobs" className="underline underline-offset-4">
          Jobs
        </Link>{" "}
        page and click “Draft now”.
      </p>
    </div>
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
      <h2 className="text-sm font-medium">Needs attention</h2>
      <ul className="flex flex-col gap-2">
        {items.map((item) => (
          <li
            key={item.id}
            className="bg-card flex flex-wrap items-center justify-between gap-2 rounded-xl border px-3 py-2 text-sm"
          >
            <div className="min-w-0">
              <p className="font-medium">
                {item.job_title ?? "Outreach"} · {item.company.name}
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

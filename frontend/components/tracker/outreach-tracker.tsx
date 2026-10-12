"use client";

import { X } from "lucide-react";
import { useEffect, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { errorMessage } from "@/lib/api";
import { selectClass } from "@/lib/jobs";
import {
  useOutreachDetail,
  useOutreachList,
  useReviewAction,
  useSetTracking,
  useTimeline,
} from "@/lib/queries";
import type { Outcome, OutreachListItem, OutreachStatus } from "@/lib/types";
import { cn } from "@/lib/utils";

type Filter = {
  key: string;
  label: string;
  statuses: OutreachStatus[];
  outcomes?: Outcome[];
};

const FILTERS: Filter[] = [
  { key: "scheduled", label: "Scheduled", statuses: ["approved", "scheduled"] },
  { key: "sent", label: "Sent", statuses: ["sent"] },
  { key: "replied", label: "Replied", statuses: ["replied"] },
  { key: "followup", label: "Follow-up due", statuses: ["followup_due"] },
  {
    key: "referred",
    label: "Referred",
    statuses: [],
    outcomes: ["referred", "interview"],
  },
  { key: "closed", label: "Closed", statuses: ["closed", "skipped", "failed"] },
];

const STATUS_LABELS: Record<OutreachStatus, string> = {
  drafting: "Drafting",
  pending_review: "In review",
  approved: "Approved",
  scheduled: "Scheduled",
  sent: "Sent",
  replied: "Replied",
  followup_due: "Follow-up due",
  send_failed: "Send failed",
  skipped: "Skipped",
  failed: "Failed",
  closed: "Closed",
};

const OUTCOMES: { value: Outcome; label: string }[] = [
  { value: "none", label: "No outcome yet" },
  { value: "referred", label: "Referred" },
  { value: "interview", label: "Interview" },
  { value: "rejected", label: "Rejected" },
  { value: "not_hiring", label: "Not hiring" },
];

function when(iso: string | null): string {
  if (!iso) return "–";
  return new Date(iso).toLocaleString(undefined, {
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function ago(iso: string): string {
  const minutes = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours} h ago`;
  return `${Math.round(hours / 24)} d ago`;
}

export function OutreachTracker() {
  const [filter, setFilter] = useState<Filter>(FILTERS[0]);
  const [openId, setOpenId] = useState<string | null>(null);
  const list = useOutreachList(filter.statuses, filter.outcomes);
  const items = list.data?.items ?? [];

  return (
    <div className="flex flex-col gap-4">
      <div
        role="tablist"
        aria-label="Outreach status"
        className="flex flex-wrap gap-1"
      >
        {FILTERS.map((f) => (
          <button
            key={f.key}
            role="tab"
            type="button"
            aria-selected={f.key === filter.key}
            onClick={() => setFilter(f)}
            className={cn(
              "rounded-full border px-3 py-1 text-sm transition-colors",
              f.key === filter.key
                ? "bg-foreground text-background border-foreground"
                : "hover:bg-muted",
            )}
          >
            {f.label}
          </button>
        ))}
      </div>

      {list.isError && (
        <p className="text-destructive text-sm">{errorMessage(list.error)}</p>
      )}
      {list.isPending && (
        <p className="text-muted-foreground py-10 text-center text-sm">
          Loading…
        </p>
      )}
      {list.data && items.length === 0 && (
        <div className="text-muted-foreground rounded-xl border border-dashed px-4 py-10 text-center text-sm">
          Nothing here yet.
        </div>
      )}

      {items.length > 0 && (
        <div className="overflow-x-auto rounded-xl border">
          <table className="w-full text-sm">
            <thead className="bg-muted/50 text-muted-foreground text-left text-xs">
              <tr>
                <th className="px-3 py-2 font-medium">Company</th>
                <th className="px-3 py-2 font-medium">Role</th>
                <th className="hidden px-3 py-2 font-medium md:table-cell">
                  Contact
                </th>
                <th className="px-3 py-2 font-medium">
                  {filter.key === "scheduled" ? "Goes out" : "Sent"}
                </th>
                <th className="hidden px-3 py-2 font-medium sm:table-cell">
                  Last activity
                </th>
                <th className="px-3 py-2 font-medium">Status</th>
              </tr>
            </thead>
            <tbody className="divide-y">
              {items.map((item) => (
                <Row
                  key={item.id}
                  item={item}
                  scheduledView={filter.key === "scheduled"}
                  onOpen={() => setOpenId(item.id)}
                />
              ))}
            </tbody>
          </table>
        </div>
      )}

      {openId && <Drawer id={openId} onClose={() => setOpenId(null)} />}
    </div>
  );
}

function Row({
  item,
  scheduledView,
  onOpen,
}: {
  item: OutreachListItem;
  scheduledView: boolean;
  onOpen: () => void;
}) {
  return (
    <tr
      className="hover:bg-muted/30 cursor-pointer"
      onClick={onOpen}
      onKeyDown={(e) => e.key === "Enter" && onOpen()}
      tabIndex={0}
    >
      <td className="px-3 py-2 font-medium">{item.company.name}</td>
      <td className="max-w-56 truncate px-3 py-2">{item.job_title ?? "–"}</td>
      <td className="hidden px-3 py-2 md:table-cell">
        {item.contact?.full_name ?? "–"}
      </td>
      <td className="px-3 py-2 whitespace-nowrap">
        {when(scheduledView ? item.scheduled_at : item.sent_at)}
      </td>
      <td className="text-muted-foreground hidden px-3 py-2 whitespace-nowrap sm:table-cell">
        {ago(item.updated_at)}
      </td>
      <td className="px-3 py-2">
        <span className="flex flex-wrap gap-1">
          <Badge variant="secondary">
            {STATUS_LABELS[item.status as OutreachStatus] ?? item.status}
          </Badge>
          {item.outcome !== "none" && (
            <Badge>
              {OUTCOMES.find((o) => o.value === item.outcome)?.label}
            </Badge>
          )}
        </span>
      </td>
    </tr>
  );
}

function Drawer({ id, onClose }: { id: string; onClose: () => void }) {
  const detail = useOutreachDetail(id);
  const timeline = useTimeline(id);
  const tracking = useSetTracking();
  const action = useReviewAction();
  const [notes, setNotes] = useState<string | null>(null);
  const data = detail.data;

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div className="fixed inset-0 z-50 flex justify-end">
      <button
        type="button"
        aria-label="Close"
        className="absolute inset-0 bg-black/30"
        onClick={onClose}
      />
      <aside
        role="dialog"
        aria-modal="true"
        aria-label="Outreach details"
        className="bg-background relative flex h-full w-full max-w-lg flex-col gap-4 overflow-y-auto border-l p-4 shadow-xl"
      >
        <div className="flex items-start justify-between gap-2">
          <div>
            <h2 className="font-semibold">
              {data?.job_title ?? data?.company.name ?? "Loading…"}
            </h2>
            {data && (
              <p className="text-muted-foreground text-sm">
                {data.company.name}
                {data.contact &&
                  ` · ${data.contact.full_name} <${data.contact.email}>`}
              </p>
            )}
          </div>
          <Button
            variant="ghost"
            size="sm"
            onClick={onClose}
            aria-label="Close"
          >
            <X />
          </Button>
        </div>

        {data && (
          <div className="flex flex-wrap items-end gap-3">
            <label className="flex flex-col gap-1 text-sm">
              <span className="text-muted-foreground text-xs">Outcome</span>
              <select
                className={selectClass}
                value={data.outcome}
                disabled={tracking.isPending}
                onChange={(e) =>
                  tracking.mutate({ id, outcome: e.target.value as Outcome })
                }
              >
                {OUTCOMES.map((o) => (
                  <option key={o.value} value={o.value}>
                    {o.label}
                  </option>
                ))}
              </select>
            </label>
            {(data.status === "approved" || data.status === "scheduled") && (
              <Button
                variant="outline"
                size="sm"
                disabled={action.isPending}
                onClick={() => action.mutate({ id, action: "unapprove" })}
                title="Take it out of the send queue and back to review"
              >
                Pull back to review
              </Button>
            )}
            {["sent", "replied", "followup_due"].includes(data.status) && (
              <Button
                variant="outline"
                size="sm"
                disabled={action.isPending}
                onClick={() => action.mutate({ id, action: "close" })}
                title="No follow-up; mark this one done"
              >
                Close
              </Button>
            )}
          </div>
        )}
        {(tracking.isError || action.isError) && (
          <p className="text-destructive text-sm">
            {errorMessage(tracking.error ?? action.error)}
          </p>
        )}

        {data && (
          <label className="flex flex-col gap-1 text-sm">
            <span className="text-muted-foreground text-xs">
              Notes (only you see these)
            </span>
            <Textarea
              rows={3}
              value={notes ?? data.notes}
              onChange={(e) => setNotes(e.target.value)}
              onBlur={() =>
                notes !== null &&
                notes !== data.notes &&
                tracking.mutate({ id, notes })
              }
            />
          </label>
        )}

        <section className="flex flex-col gap-2">
          <h3 className="text-sm font-medium">History</h3>
          <ol className="flex flex-col gap-3 border-l pl-4">
            {timeline.data?.map((entry, i) => (
              <li key={`${entry.at}-${i}`} className="relative text-sm">
                <span className="bg-foreground absolute top-1.5 -left-[1.3rem] size-2 rounded-full" />
                <p className="flex flex-wrap gap-x-2">
                  <span className="font-medium">{entry.title}</span>
                  <span className="text-muted-foreground">
                    {when(entry.at)}
                  </span>
                </p>
                {entry.reason && entry.type !== "scheduled" && (
                  <p className="text-muted-foreground">{entry.reason}</p>
                )}
                {entry.text && (
                  <p className="bg-muted/40 mt-1 rounded-md border p-2 whitespace-pre-wrap">
                    {entry.text}
                  </p>
                )}
              </li>
            ))}
          </ol>
        </section>
      </aside>
    </div>
  );
}

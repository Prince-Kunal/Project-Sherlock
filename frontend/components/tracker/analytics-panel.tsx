"use client";

import { useState } from "react";

import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { errorMessage } from "@/lib/api";
import { selectClass } from "@/lib/jobs";
import {
  useAnalytics,
  usePreferences,
  useSavePreferences,
} from "@/lib/queries";
import {
  type AnalyticsBucket,
  type OutreachAnalytics,
  STYLE_NAMES,
} from "@/lib/types";

const RANGES = [
  { days: 30, label: "Last 30 days" },
  { days: 90, label: "Last 90 days" },
  { days: 365, label: "Last year" },
  { days: null, label: "All time" },
] as const;

function Tile({
  label,
  value,
  note,
}: {
  label: string;
  value: string;
  note?: string;
}) {
  return (
    <div className="bg-surface ring-foreground/[0.07] shadow-soft rounded-2xl px-5 py-4 ring-1">
      <p className="text-muted-foreground text-xs">{label}</p>
      <p className="text-2xl font-semibold tabular-nums">{value}</p>
      {note && <p className="text-muted-foreground text-xs">{note}</p>}
    </div>
  );
}

/** Reply rate per group: one bar per row (one hue: it's a magnitude), the numbers written beside it. */
function RateTable({
  title,
  rows,
}: {
  title: string;
  rows: AnalyticsBucket[];
}) {
  if (rows.length === 0) return null;
  return (
    <figure className="flex flex-col gap-2">
      <figcaption className="text-sm font-medium">{title}</figcaption>
      <table className="w-full text-sm">
        <thead className="sr-only">
          <tr>
            <th>Group</th>
            <th>Reply rate</th>
            <th>Replies of sent</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr
              key={row.key}
              title={`${row.label}: ${row.replied} replies to ${row.sent} emails${
                row.referred ? `, ${row.referred} referred` : ""
              }${row.interview ? `, ${row.interview} interviews` : ""}`}
            >
              <td className="w-36 py-1 pr-3 align-middle whitespace-nowrap">
                {row.label}
              </td>
              <td className="py-1 align-middle">
                <div className="bg-muted h-2 rounded-full">
                  <div
                    className="bg-primary h-2 rounded-full"
                    style={{ width: `${Math.max(row.reply_rate ?? 0, 0.5)}%` }}
                  />
                </div>
              </td>
              <td className="text-muted-foreground w-32 py-1 pl-3 text-right align-middle whitespace-nowrap tabular-nums">
                {row.reply_rate ?? 0}% · {row.replied}/{row.sent}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </figure>
  );
}

function StyleSetting({ data }: { data: OutreachAnalytics }) {
  const prefs = usePreferences();
  const save = useSavePreferences();
  return (
    <div className="flex flex-col gap-2">
      <p className="text-sm">{data.verdict}</p>
      <label className="flex flex-wrap items-center gap-2 text-sm">
        New drafts use
        <select
          className={selectClass}
          value={prefs.data?.draft_style ?? data.draft_style}
          disabled={!prefs.data || save.isPending}
          onChange={(e) =>
            prefs.data &&
            save.mutate({
              ...prefs.data,
              draft_style: e.target.value as "ab" | "a" | "b",
            })
          }
        >
          <option value="ab">both styles, to compare them</option>
          <option value="a">{STYLE_NAMES.a} only</option>
          <option value="b">{STYLE_NAMES.b} only</option>
        </select>
      </label>
      <p className="text-muted-foreground text-xs">
        {STYLE_NAMES.a}: the ask comes in the first sentence. {STYLE_NAMES.b}:
        it opens with the one thing you built that&apos;s closest to their work,
        then asks.
      </p>
      {save.isError && (
        <p className="text-destructive text-sm">{errorMessage(save.error)}</p>
      )}
    </div>
  );
}

/** Phase 10: who replies, at which companies, to which style of email. */
export function AnalyticsPanel() {
  const [days, setDays] = useState<number | null>(90);
  const analytics = useAnalytics(days);
  const data = analytics.data;

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between gap-2">
        <p className="text-muted-foreground text-sm">
          First emails only. A reply is any answer from a person.
        </p>
        <select
          aria-label="Time range"
          className={selectClass}
          value={days ?? "all"}
          onChange={(e) =>
            setDays(e.target.value === "all" ? null : Number(e.target.value))
          }
        >
          {RANGES.map((r) => (
            <option key={r.label} value={r.days ?? "all"}>
              {r.label}
            </option>
          ))}
        </select>
      </div>
      {analytics.isError && (
        <p className="text-destructive text-sm">
          {errorMessage(analytics.error)}
        </p>
      )}
      {data && (
        <>
          <div className="grid gap-2 sm:grid-cols-3">
            <Tile label="Emails sent" value={String(data.sent)} />
            <Tile
              label="Reply rate"
              value={data.reply_rate === null ? "–" : `${data.reply_rate}%`}
              note={`${data.replied} replies`}
            />
            <Tile
              label="Referrals and interviews"
              value={String(data.referred + data.interview)}
              note={`${data.referred} referred · ${data.interview} interviews`}
            />
          </div>
          <Card>
            <CardHeader>
              <CardTitle>Which email style works</CardTitle>
              <CardDescription>
                Drafts alternate between two styles so you can see which one
                people answer.
              </CardDescription>
            </CardHeader>
            <CardContent className="flex flex-col gap-4">
              <RateTable title="By style" rows={data.by_variant} />
              <StyleSetting data={data} />
            </CardContent>
          </Card>
          {data.sent > 0 ? (
            <Card>
              <CardHeader>
                <CardTitle>Who replies</CardTitle>
              </CardHeader>
              <CardContent className="grid gap-6 lg:grid-cols-3">
                <RateTable title="By contact role" rows={data.by_role} />
                <RateTable title="By company size" rows={data.by_stage} />
                <RateTable title="By mode" rows={data.by_mode} />
              </CardContent>
            </Card>
          ) : (
            <p className="text-muted-foreground text-sm">
              Nothing sent in this period yet.
            </p>
          )}
        </>
      )}
    </div>
  );
}

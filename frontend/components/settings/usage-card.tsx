"use client";

import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { useQuota } from "@/lib/queries";
import { cn } from "@/lib/utils";

function Meter({
  label,
  used,
  limit,
  format = String,
}: {
  label: string;
  used: number;
  limit: number;
  format?: (n: number) => string;
}) {
  const share = limit > 0 ? Math.min(1, used / limit) : 1;
  const full = used >= limit && limit >= 0 && used > 0;
  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex items-baseline justify-between text-sm">
        <span>{label}</span>
        <span className="text-muted-foreground tabular-nums">
          {format(used)} of {format(limit)}
        </span>
      </div>
      <div
        className="bg-muted h-2 overflow-hidden rounded-full"
        role="meter"
        aria-label={label}
        aria-valuemin={0}
        aria-valuemax={limit}
        aria-valuenow={used}
      >
        <div
          className={cn(
            "h-full rounded-full",
            full ? "bg-destructive" : "bg-primary",
          )}
          style={{ width: `${share * 100}%` }}
        />
      </div>
    </div>
  );
}

/** Phase 9: this month's usage against the per-user quotas. */
export function UsageCard() {
  const quota = useQuota();
  const q = quota.data;
  if (!q) return null;
  const usd = (n: number) => `$${n.toFixed(2)}`;

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          This month
          {q.exceeded.length > 0 && (
            <Badge variant="destructive">Limit reached</Badge>
          )}
        </CardTitle>
        <CardDescription>
          Each person has a monthly allowance so nobody uses up the group&apos;s
          credits. It resets on{" "}
          {new Date(q.resets_at).toLocaleDateString(undefined, {
            day: "numeric",
            month: "long",
          })}
          .
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <Meter
          label="Contact lookups"
          used={q.contact_lookups}
          limit={q.contact_lookups_limit}
        />
        <Meter
          label="AI spend (estimated)"
          used={Number(q.llm_usd)}
          limit={Number(q.llm_usd_limit)}
          format={usd}
        />
        {q.message && <p className="text-destructive text-sm">{q.message}</p>}
      </CardContent>
    </Card>
  );
}

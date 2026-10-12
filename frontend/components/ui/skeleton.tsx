import { cn } from "@/lib/utils";

/** A placeholder in the shape of what's loading, with a slow shimmer. */
function Skeleton({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="skeleton"
      aria-hidden="true"
      className={cn("bg-muted animate-pulse rounded-lg", className)}
      {...props}
    />
  );
}

/** Rows of skeleton cards for a list that's loading (announced to screen readers once). */
function ListSkeleton({
  rows = 3,
  label = "Loading",
}: {
  rows?: number;
  label?: string;
}) {
  return (
    <div role="status" aria-label={label} className="flex flex-col gap-2">
      {Array.from({ length: rows }, (_, i) => (
        <div
          key={i}
          className="bg-card flex gap-4 rounded-2xl border p-4"
          style={{ opacity: 1 - i * 0.22 }}
        >
          <Skeleton className="size-11 shrink-0 rounded-xl" />
          <div className="flex flex-1 flex-col gap-2 pt-1">
            <Skeleton className="h-4 w-2/5" />
            <Skeleton className="h-3 w-3/5" />
            <Skeleton className="h-3 w-1/4" />
          </div>
        </div>
      ))}
    </div>
  );
}

export { Skeleton, ListSkeleton };

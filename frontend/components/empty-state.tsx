import { CanonLine } from "@/components/brand";
import type { CanonQuote } from "@/lib/canon";
import { cn } from "@/lib/utils";

/** An empty list, composed: what's missing, how to fill it, and a line from the canon. */
export function EmptyState({
  title,
  children,
  quote,
  actions,
  className,
}: {
  title: string;
  children?: React.ReactNode;
  quote?: CanonQuote;
  actions?: React.ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "bg-surface/60 relative overflow-hidden rounded-2xl border border-dashed px-6 py-10 sm:px-10 sm:py-12",
        className,
      )}
    >
      <div className="grid gap-8 md:grid-cols-[1fr_auto] md:items-end">
        <div className="max-w-[60ch]">
          <h2 className="text-xl font-semibold tracking-tight">{title}</h2>
          {children && (
            <div className="text-muted-foreground mt-2 text-sm leading-relaxed">
              {children}
            </div>
          )}
          {actions && (
            <div className="mt-5 flex flex-wrap items-center gap-2">
              {actions}
            </div>
          )}
        </div>
        {quote && (
          <CanonLine
            {...quote}
            className="border-brand/60 max-w-[34ch] border-l-2 pl-4 md:mb-1"
          />
        )}
      </div>
    </div>
  );
}

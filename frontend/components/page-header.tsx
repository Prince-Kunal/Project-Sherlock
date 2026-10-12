import { cn } from "@/lib/utils";

/** The top of every app page: title, one line of context, and the page's actions. */
export function PageHeader({
  title,
  description,
  actions,
  className,
}: {
  title: string;
  description?: React.ReactNode;
  actions?: React.ReactNode;
  className?: string;
}) {
  return (
    <header
      className={cn(
        "flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between",
        className,
      )}
    >
      <div className="min-w-0">
        <h1 className="text-3xl leading-tight font-semibold tracking-[-0.03em] sm:text-[2.1rem]">
          {title}
        </h1>
        {description && (
          <p className="text-muted-foreground mt-1.5 max-w-[65ch] text-[0.95rem] leading-relaxed">
            {description}
          </p>
        )}
      </div>
      {actions && (
        <div className="flex shrink-0 flex-wrap items-center gap-2">
          {actions}
        </div>
      )}
    </header>
  );
}

import { cn } from "@/lib/utils";

/** The mark: a lens on a handle, the one geometric shape the brand owns. */
export function BrandMark({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 32 32"
      aria-hidden="true"
      className={cn("size-7 shrink-0", className)}
    >
      <circle cx="13.5" cy="13.5" r="8.5" fill="var(--brand)" opacity="0.18" />
      <circle
        cx="13.5"
        cy="13.5"
        r="8.5"
        fill="none"
        stroke="var(--brand)"
        strokeWidth="2.4"
      />
      <path
        d="M20 20l7 7"
        stroke="currentColor"
        strokeWidth="3"
        strokeLinecap="round"
      />
    </svg>
  );
}

export function Wordmark({ className }: { className?: string }) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-2 text-[1.05rem] font-semibold tracking-tight",
        className,
      )}
    >
      <BrandMark />
      Sherlock
    </span>
  );
}

/** A quotation from the canon, set in the period serif. */
export function CanonLine({
  text,
  source,
  className,
}: {
  text: string;
  source: string;
  className?: string;
}) {
  return (
    <figure className={cn("max-w-[52ch]", className)}>
      <blockquote className="font-serif text-lg leading-snug italic">
        &ldquo;{text}&rdquo;
      </blockquote>
      <figcaption className="text-muted-foreground mt-1.5 text-xs">
        Sherlock Holmes, <cite className="not-italic">{source}</cite>
      </figcaption>
    </figure>
  );
}

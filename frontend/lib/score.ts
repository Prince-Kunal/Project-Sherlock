/**
 * Fit scores (0-100) as a tile. Only the strongest matches get the brand colour; the rest step
 * down through ink and fog, so the eye goes to the best fits first.
 */
export function scoreClass(score: number | null): string {
  const base =
    "flex shrink-0 items-center justify-center rounded-xl font-mono font-semibold tabular";
  if (score === null) return `${base} bg-muted text-muted-foreground`;
  if (score >= 85) return `${base} bg-brand text-brand-foreground shadow-soft`;
  if (score >= 70) return `${base} bg-primary text-primary-foreground`;
  if (score >= 50)
    return `${base} bg-muted text-foreground ring-1 ring-foreground/10 ring-inset`;
  return `${base} bg-muted text-muted-foreground`;
}

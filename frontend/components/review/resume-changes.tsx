import type { ResumeChange } from "@/lib/types";

const LABELS: Record<ResumeChange["change"], string> = {
  rephrased: "Rephrased",
  reordered: "Moved",
  removed: "Left out",
  added: "Added",
};

/** Side-by-side before/after of every bullet the tailoring changed. */
export function ResumeChanges({ changes }: { changes: ResumeChange[] }) {
  if (changes.length === 0) {
    return (
      <p className="text-muted-foreground text-sm">
        No changes from your master resume.
      </p>
    );
  }
  return (
    <div className="overflow-hidden rounded-lg border text-sm">
      <div className="bg-muted/50 text-muted-foreground grid grid-cols-[5rem_1fr_1fr] gap-3 px-3 py-2 text-xs font-medium">
        <span />
        <span>Master resume</span>
        <span>Tailored</span>
      </div>
      <ul className="divide-y">
        {changes.map((c) => (
          <li
            key={c.bullet_id}
            className="grid grid-cols-[5rem_1fr_1fr] gap-3 px-3 py-2"
          >
            <span className="text-muted-foreground text-xs">
              {LABELS[c.change]}
            </span>
            <span
              className={
                c.change === "rephrased" || c.change === "removed"
                  ? "text-muted-foreground"
                  : undefined
              }
            >
              {c.before ?? "—"}
            </span>
            <span>
              {c.change === "removed" ? (
                <span className="text-muted-foreground">—</span>
              ) : (
                (c.after ?? c.before)
              )}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

import { Users } from "lucide-react";

import type { WarmPath } from "@/lib/types";

function describe(path: WarmPath): string {
  const people = path.people
    .map(
      (p) =>
        `${p.name}${p.position ? ` (${p.position})` : ""}${p.alumni ? ", your college" : ""}`,
    )
    .join("; ");
  const more =
    path.count > path.people.length
      ? `; and ${path.count - path.people.length} more`
      : "";
  return people + more;
}

/** "You know 2 people here" (Phase 10 warm paths), names on hover. Sherlock never emails them. */
export function WarmPathBadge({ path }: { path: WarmPath | null }) {
  if (!path || path.count === 0) return null;
  return (
    <span
      className="inline-flex items-center gap-1 rounded-md bg-emerald-50 px-1.5 py-0.5 text-[0.72rem] font-medium text-emerald-800 dark:bg-emerald-950/50 dark:text-emerald-300"
      title={describe(path)}
    >
      <Users className="size-3" />
      You know {path.count === 1 ? "1 person" : `${path.count} people`} here
      {path.alumni > 0 && ` · ${path.alumni} from your college`}
    </span>
  );
}

/** The fuller version for the review card. */
export function WarmPathNote({
  path,
  knowsContact,
}: {
  path: WarmPath | null;
  knowsContact: boolean;
}) {
  if (!path || path.count === 0) return null;
  return (
    <div className="rounded-2xl border border-emerald-200 bg-emerald-50/70 px-4 py-3 text-sm text-emerald-950 dark:border-emerald-900 dark:bg-emerald-950/30 dark:text-emerald-100">
      <p className="flex items-center gap-1.5 font-medium">
        <Users className="size-4" />
        {knowsContact
          ? "You already know the person this is addressed to."
          : `You know ${path.count === 1 ? "someone" : `${path.count} people`} at this company.`}
      </p>
      <ul className="mt-1 flex flex-col gap-0.5">
        {path.people.map((p) => (
          <li key={`${p.name}-${p.position}`}>
            {p.profile_url ? (
              <a
                className="underline-offset-4 hover:underline"
                href={p.profile_url}
                target="_blank"
                rel="noreferrer"
              >
                {p.name}
              </a>
            ) : (
              p.name
            )}
            {p.position && <span className="opacity-75"> · {p.position}</span>}
            {p.alumni && <span className="opacity-75"> · your college</span>}
          </li>
        ))}
      </ul>
      <p className="mt-1 text-xs opacity-80">
        A message from you to them may get further than a cold email. Sherlock
        won&apos;t contact them.
      </p>
    </div>
  );
}

import { cn } from "@/lib/utils";

/** A plain data table that scrolls sideways on narrow screens instead of the page. */
export function DataTable({
  head,
  children,
  className,
}: {
  head: React.ReactNode[];
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("overflow-x-auto rounded-xl border", className)}>
      <table className="w-full min-w-[640px] text-sm">
        <thead className="bg-muted/60 text-muted-foreground text-left text-xs">
          <tr>
            {head.map((cell, i) => (
              <th key={i} className="px-3 py-2 font-medium whitespace-nowrap">
                {cell}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y">{children}</tbody>
      </table>
    </div>
  );
}

export function Cell({
  children,
  className,
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return <td className={cn("px-3 py-2 align-top", className)}>{children}</td>;
}

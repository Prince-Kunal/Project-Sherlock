import type { EmploymentType } from "@/lib/types";

export const TYPE_LABELS: Record<EmploymentType, string> = {
  internship: "Internship",
  full_time: "Full-time",
  part_time: "Part-time",
  contract: "Contract",
};

export const SOURCE_LABELS: Record<string, string> = {
  greenhouse: "Greenhouse",
  lever: "Lever",
  ashby: "Ashby",
  adzuna: "Adzuna",
  hn: "HN",
  manual: "Added by URL",
};

export function age(days: number): string {
  if (days === 0) return "today";
  if (days === 1) return "1 day";
  return `${days} days`;
}

export const selectClass =
  "border-input h-8 rounded-lg border bg-transparent px-2 text-sm";

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
  smartrecruiters: "SmartRecruiters",
  workable: "Workable",
  recruitee: "Recruitee",
  adzuna: "Adzuna",
  hn: "HN",
  remotive: "via Remotive",
  manual: "Added by URL",
};

export function age(days: number): string {
  if (days === 0) return "today";
  if (days === 1) return "1 day";
  return `${days} days`;
}

export const selectClass =
  "border-input bg-surface h-9 rounded-[10px] border px-2.5 text-sm transition-[border-color,box-shadow] duration-200 outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50";
